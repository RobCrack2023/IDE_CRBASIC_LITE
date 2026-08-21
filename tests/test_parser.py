"""Pruebas de fidelidad del port contra el comportamiento del firmware.

Cada caso está anclado a una línea concreta de OptaPakBus.ino. Si el
firmware cambia, estas pruebas son las que tienen que fallar primero.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic import analyze, parse  # noqa: E402
from optabasic.expr import compile_expr  # noqa: E402
from optabasic.lexer import args_of, keyword, paren, split_lines  # noqa: E402
from optabasic.model import StmtType  # noqa: E402

EJEMPLOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "ejemplos")


def codigos(resultado):
    return {d.code for d in resultado.diagnostics}


# ── Lexer ────────────────────────────────────────────────────────────────
def test_keyword_corta_en_parentesis_y_espacio():
    assert keyword("  VoltSE(X, 1)") == "VOLTSE"
    assert keyword("StationName=Casa") == "STATIONNAME=CASA"
    assert keyword("") == ""


def test_paren_toma_hasta_el_ultimo_cierre():
    assert paren("Sample(1, Abs(X), FP2)") == "1, Abs(X), FP2"


def test_args_respeta_anidados_y_corta_en_parentesis_huerfano():
    args, _, _ = args_of("1, Abs(X + 1), FP2")
    assert args == ["1", "Abs(X + 1)", "FP2"]
    # El ')' huérfano corta ese argumento, pero el bucle sigue con el resto.
    args, _, _ = args_of("A) sobra")
    assert args == ["A", "sobra"]


def test_args_trunca_a_31_caracteres():
    largo = "N" * 40
    args, crudos, _ = args_of(f"1, {largo}")
    assert len(args[1]) == 31
    assert len(crudos[1]) == 40


def test_lineas_en_blanco_no_cuentan_para_el_firmware():
    """El firmware consume todos los saltos juntos (OptaPakBus.ino:2493)."""
    lineas = split_lines("A\n\n\nB\n")
    assert [(l.file_no, l.fw_no) for l in lineas] == [(1, 1), (4, 2)]


def test_comentario_respeta_comillas():
    lineas = split_lines("StationName=\"no ' es comentario\" ' esto si\n")
    assert lineas[0].text == 'StationName="no \' es comentario"'


# ── Expresiones ──────────────────────────────────────────────────────────
def _compilar(expr, variables=("A", "B"), constantes=("K",)):
    return compile_expr(expr, list(variables), list(constantes), 20, 20)


def test_expresion_simple_cuenta_tokens_rpn():
    assert _compilar("A + B").tokens == 3          # A B +
    assert _compilar("A * 2 + B").tokens == 5      # A 2 * B +


def test_funciones_soportadas_y_no_soportadas():
    assert _compilar("Sqr(A)").ok
    assert _compilar("Abs(A - B)").ok
    r = _compilar("Sin(A)")
    assert not r.ok and "Abs, Int y Sqr" in r.error


def test_identificador_no_declarado_rompe_la_expresion():
    r = _compilar("A + Desconocida")
    assert not r.ok and r.unknown == "Desconocida"


def test_limite_de_20_tokens():
    assert not _compilar("A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A+A").ok


def test_parentesis_sin_cerrar():
    assert not _compilar("(A + B").ok


def test_dos_operandos_seguidos():
    assert not _compilar("A B").ok


# ── Reglas del firmware ──────────────────────────────────────────────────
def test_sin_datatable_el_programa_no_se_ejecuta():
    """crParsed = (crTableCount > 0) — OptaPakBus.ino:2967."""
    r = analyze("Public X\nScan(10, Sec)\n")
    assert not r.program.parsed
    assert "sin-datatable" in codigos(r)


def test_public_indentado_registra_variable_espuria():
    """El firmware avanza desde la columna 0 — OptaPakBus.ino:2598."""
    r = parse("    Public Nivel\n")
    assert [v.name for v in r.program.vars] == ["Public", "Nivel"]
    assert "declaracion-indentada" in codigos(analyze("    Public Nivel\n"))


def test_const_si_tolera_indentacion():
    """cr_const salta la indentación antes del offset — OptaPakBus.ino:2510."""
    r = parse("    Const K = 2.5\n")
    assert [c.name for c in r.program.consts] == ["K"]
    assert r.program.consts[0].value == 2.5


def test_asignacion_indentada_funciona_desde_v1_6_8():
    """El firmware ahora salta la sangría antes de recortar el destino.

    Hasta v1.6.8 esta línea se descartaba entera: el destino se tomaba
    desde la columna 0 y cr_find_var() compara exacto.
    """
    fuente = ("Public A, B\nDataTable(T,True,1)\nDataInterval(0,1,Min,0)\n"
              "Sample(1,A,FP2)\nEndTable\n    A = B + 1\n")
    r = analyze(fuente)
    assert len(r.program.stmts) == 1
    assert r.program.stmts[0].dest_var == 0
    assert "asignacion-indentada" not in codigos(r)
    assert "fw-asign-var" not in codigos(r)


def test_sangria_ya_no_come_caracteres_del_nombre():
    """Antes la sangría gastaba parte de los 23 caracteres del destino."""
    nombre = "N" * 23
    fuente = f"Public {nombre}\n            {nombre} = 1\n"
    r = parse(fuente)
    assert len(r.program.stmts) == 1


def test_asignacion_dentro_de_if_si_tolera_indentacion():
    """El destino sale de `body`, ya sin sangría — OptaPakBus.ino:2430."""
    fuente = "Public A, B\n    If (B > 1) Then A = B + 1\n"
    r = parse(fuente)
    assert len(r.program.stmts) == 1
    assert r.program.stmts[0].dest_var == 0


def test_units_ma_marca_canal_4_20():
    r = parse("Public Caudal\nUnits Caudal = mA\n")
    assert r.program.vars[0].is4_20mA
    assert r.program.vars[0].pin == 0


def test_units_ma_mas_asignacion_pierde_el_canal():
    """noAutoPin solo se revierte para hasVoltInstr — OptaPakBus.ino:2917."""
    fuente = "Public Caudal\nUnits Caudal = mA\nCaudal = Caudal * 2\n"
    r = analyze(fuente)
    assert r.program.vars[0].pin == -1
    assert "units-ma-sin-canal" in codigos(r)


def test_canal_explicito_queda_reservado():
    """Desde v1.6.9 used[] se pre-marca con los canales comprometidos.

    Antes el reparto secuencial volvía a entregar un canal ya fijado a
    mano y las dos variables terminaban leyendo el mismo borne.
    """
    fuente = ("Public Temp\nPublic Caudal\nUnits Caudal = mA\n"
              "VoltSE(Temp, 1, mV5000, 1, 0, 0, 1.0, 0.0)\n")
    r = analyze(fuente)
    assert r.program.find_var("Temp").pin == 0
    assert r.program.find_var("Caudal").pin == 1
    assert "colision-canal" not in codigos(r)


def test_pulsecount_tambien_reserva_su_canal():
    fuente = ("Public Lluvia\nPublic Nivel\nUnits Nivel = mA\n"
              "PulseCount(Lluvia, 1, P1, 2, 0, 0.2, 0.0)\n")
    r = analyze(fuente)
    assert r.program.find_var("Lluvia").pulse_pin == 0
    assert r.program.find_var("Nivel").pin == 1


def test_excitech_reserva_el_canal():
    fuente = "Public Nivel\nUnits Nivel = mA\nExciteCh(1)\n"
    r = analyze(fuente)
    assert 0 in r.program.excite_channels
    assert r.program.find_var("Nivel").pin == 1


def test_excitech_fuera_de_rango():
    assert "fw-excitech-rango" in codigos(analyze("ExciteCh(9)\n"))


# ── Battery, real desde v1.6.9 ───────────────────────────────────────────
def test_battery_con_canal_explicito():
    r = parse("Public BattV\nBattery(BattV, 3)\n")
    v = r.program.find_var("BattV")
    assert v.is_batt_v and v.pin == 2 and v.no_auto_pin


def test_battery_sin_canal_usa_el_borne_8():
    for fuente in ("Public V_alim\nBattery(V_alim)\n",
                   "Public V_alim\nBattery(V_alim, 0)\n"):
        v = parse(fuente).program.find_var("V_alim")
        assert v.is_batt_v and v.pin == 7


def test_battery_fuera_de_rango_avisa_y_cae_al_8():
    r = analyze("Public BattV\nBattery(BattV, 12)\n")
    assert "fw-battery-rango" in codigos(r)
    assert r.program.find_var("BattV").pin == 7


def test_battery_sin_argumentos_sigue_siendo_noop():
    r = analyze("Battery()\n")
    assert not any(d.code.startswith("fw-battery") for d in r.diagnostics)


def test_att_pierde_a7_si_esta_ocupado():
    fuente = "Public Otro\nPublic BattV\nBattery(Otro, 8)\n"
    r = analyze(fuente)
    assert r.program.find_var("BattV").pin == -1
    assert "att-sin-canal" in codigos(r)


# ── PulseEdge ────────────────────────────────────────────────────────────
def test_pulse_edge_por_defecto_es_rising():
    """El default pasó de FALLING a RISING en v1.6.9."""
    r = parse("Public L\nPulseCount(L, 1, P1, 2, 0, 0.2, 0.0)\n")
    assert r.program.find_var("L").pulse_edge == "RISING"


@pytest.mark.parametrize("valor,esperado", [
    ("Rising", "RISING"), ("Subida", "RISING"), ("1", "RISING"),
    ("Falling", "FALLING"), ("Bajada", "FALLING"), ("0", "FALLING"),
])
def test_pulse_edge_acepta_las_dos_formas(valor, esperado):
    r = parse(f"Public L\nPulseCount(L, 1, P1, 2, 0, 0.2, 0.0)\n"
              f"PulseEdge(L, {valor})\n")
    assert r.program.find_var("L").pulse_edge == esperado


def test_pulse_edge_valor_invalido():
    r = analyze("Public L\nPulseCount(L,1,P1,2,0,0.2,0.0)\nPulseEdge(L, Costado)\n")
    assert "fw-pulseedge-valor" in codigos(r)


def test_pulsecount_con_offset_avisa():
    """El firmware lo registra desde v1.6.9: rompe Totalize."""
    r = analyze("Public L\nPulseCount(L, 1, P1, 2, 0, 0.2, 1.5)\n")
    assert "fw-pulse-offset" in codigos(r)


def test_battv_toma_a7_por_el_nombre():
    r = parse("Public BattV\nPublic Caudal\nUnits Caudal = mA\n")
    assert r.program.find_var("BattV").pin == 7
    assert r.program.find_var("BattV").is_batt_v
    assert r.program.find_var("Caudal").pin == 0


def test_battv_con_units_ma_pierde_el_truco():
    """La rama de batería excluye is4_20mA — OptaPakBus.ino:2924."""
    r = analyze("Public BattV\nUnits BattV = mA\n")
    assert not r.program.find_var("BattV").is_batt_v
    assert "att-con-lectura" in codigos(r)


def test_portset_es_un_statement_ejecutable():
    """Desde v1.7.0 PortSet(Rele, Valor) es una instrucción, no un vínculo."""
    r = parse("Public Bomba\nPortSet(2, Bomba)\n")
    st = r.program.stmts[-1]
    assert st.type == StmtType.PORTSET
    assert st.relay == 1                 # relé 2 → índice 1
    assert st.expr_text == "Bomba"
    assert r.program.relay_map()[1] == [st]


def test_portset_dentro_de_un_if_de_una_linea():
    """El cuerpo del If puede ser un PortSet, que no lleva '='."""
    r = parse("Public Nivel\nIf (Nivel > 5) Then PortSet(1, 1)\n")
    st = r.program.stmts[-1]
    assert st.type == StmtType.PORTSET
    assert st.relay == 0
    assert st.cond is not None           # la condición no se pierde


def test_portset_con_variable_es_la_forma_vieja():
    """PortSet(Variable, valor) era el modelo <=v1.6.18: ya no acciona nada."""
    r = parse("Public Bomba\nPortSet(Bomba, 1)\n")
    assert "fw-portset-forma-vieja" in codigos(r)
    assert not r.program.stmts


def test_portset_fuera_de_rango():
    r = parse("Public Bomba\nPortSet(9, Bomba)\n")
    assert "fw-portset-rango" in codigos(r)
    assert not r.program.stmts


def test_variable_con_nombre_de_rele_sin_portset_avisa():
    """La trampa de migrar: DO1 = 1 ya no mueve el relé por sí solo."""
    r = analyze("Public DO1\nDO1 = 1\n")
    assert "rele-sin-portset" in codigos(r)


def test_voltdiff_ignora_mult_con_menos_de_6_argumentos():
    """OptaPakBus.ino:2732."""
    r = analyze("Public V\nVoltSE(V, 1, mV5000, 1, 2.5)\n")
    assert r.program.find_var("V").mult == 1.0
    assert "volt-sin-escala" in codigos(r)


def test_tabla_sin_datainterval_no_archiva():
    fuente = "Public A\nDataTable(T, True, 100)\nSample(1, A, FP2)\nEndTable\n"
    r = analyze(fuente)
    assert r.program.tables[0].interval_sec == 0
    assert "tabla-sin-intervalo" in codigos(r)


def test_tabla_size_negativo_usa_capacidad_por_defecto():
    fuente = "Public A\nDataTable(T, True, -1)\nDataInterval(0,1,Min,0)\nSample(1,A,FP2)\nEndTable\n"
    r = parse(fuente)
    assert r.program.tables[0].size == 50000


def test_const_con_expresion_queda_en_atof_parcial():
    r = analyze("Const A = 2.0\nConst B = A * 2\n")
    assert r.program.find_const("B").value == 0.0
    assert "const-no-literal" in codigos(r)


def test_scan_minimo_un_segundo():
    assert parse("Scan(0, Sec)\n").program.scan_interval_ms == 1000
    assert parse("Scan(5, Min)\n").program.scan_interval_ms == 300000


def test_msec_se_lee_como_segundos():
    """cr_to_sec() solo conoce MIN/HOU/DAY; el resto cae a segundos."""
    r = analyze("Scan(500, Msec)\n")
    assert r.program.scan_interval_ms == 500000      # 500 s, no 0,5 s
    assert "unidad-no-reconocida" in codigos(r)


def test_if_de_una_linea_no_lleva_endif():
    fuente = "Public A, B\nIf (B > 1) Then A = 1\nEndIf\n"
    r = analyze(fuente)
    assert "endif-suelto" in codigos(r)


def test_tercer_nivel_de_if_no_evalua_condicion():
    fuente = ("Public A, B\nIf (B > 1) Then\nIf (B > 2) Then\nIf (B > 3) Then\n"
              "A = 1\nEndIf\nEndIf\nEndIf\n")
    assert "if-muy-anidado" in codigos(analyze(fuente))


def test_and_or_mezclados():
    fuente = "Public A, B, C\nIf (A > 1) AND (B > 2) OR (C > 3) Then A = 1\n"
    assert "and-or-mezclados" in codigos(analyze(fuente))


def test_tres_condiciones():
    fuente = "Public A, B, C\nIf (A > 1) AND (B > 2) AND (C > 3) Then A = 1\n"
    assert "demasiadas-condiciones" in codigos(analyze(fuente))


def test_else_if_en_dos_palabras():
    fuente = "Public A, B\nIf (B > 1) Then\nA = 1\nElse If (B > 2) Then\nA = 2\nEndIf\n"
    assert "else-if-separado" in codigos(analyze(fuente))


def test_linea_de_mas_de_127_caracteres():
    fuente = "Public A\nA = " + " + ".join(["1"] * 40) + "\n"
    assert "linea-larga" in codigos(analyze(fuente))


def test_arreglo_se_descarta():
    r = analyze("Public Temp(4)\n")
    assert [v.name for v in r.program.vars] == ["Temp"]
    assert "arreglo-descartado" in codigos(r)


def test_sufijos_de_tipo_no_crean_variables():
    r = parse("Dim A, B As Float\n")
    assert [v.name for v in r.program.vars] == ["A", "B"]


def test_instruccion_fuera_de_alcance():
    r = analyze("Public A\nFor i = 1 To 10\n")
    assert any("For/Next" in d.message for d in r.diagnostics)


def test_directivas_de_red():
    fuente = "StationName=Casa\nServerHost=ejemplo.com\nServerPort=6786\nPakBusAddress=7\n"
    net = parse(fuente).program.network
    assert net.station_name == "Casa"
    assert net.server_host == "ejemplo.com"
    assert net.server_port == 6786
    assert net.pakbus_address == 7
    assert net.provisioned


def test_serverport_fuera_de_rango_no_provisiona():
    r = analyze("ServerPort=99999\n")
    assert not r.program.network.provisioned
    assert "fw-directiva-rango" in codigos(r)


# ── Programas reales del firmware ────────────────────────────────────────
@pytest.mark.parametrize("nombre", ["programa_compuerta.CR1", "programa_opta.CR1"])
def test_ejemplos_reales_se_parsean(nombre):
    ruta = os.path.join(EJEMPLOS, nombre)
    if not os.path.exists(ruta):
        pytest.skip(f"falta {nombre}")
    from optabasic.encoding import leer

    texto, _ = leer(ruta)
    r = analyze(texto)
    assert r.program.vars
    assert r.program.tables
    # Con el firmware 1.6.12 los dos programas quedan sin errores: las
    # asignaciones indentadas ya se leen bien y los canales explícitos
    # quedan reservados.
    errores = [d for d in r.diagnostics if d.severity.value == "error"]
    assert not errores, [f"L{d.line}: {d.message}" for d in errores]


def test_diagnostico_usa_dos_variables_en_el_mismo_canal():
    """Patrón legítimo: el mismo borne en mA y en volts crudos."""
    ruta = os.path.join(EJEMPLOS, "programa_diagnostico.CR1")
    if not os.path.exists(ruta):
        pytest.skip("falta el ejemplo")
    from optabasic.encoding import leer

    texto, _ = leer(ruta)
    r = analyze(texto)
    assert "canal-compartido" in codigos(r)
    assert "colision-canal" not in codigos(r)


# ── Extensiones del router Teltonika (v1.6.14 / v1.6.18) ────────────────

def test_router_user_y_pass_son_directivas():
    """RouterUser=/RouterPass= configuran el RUT200 de cada equipo."""
    r = parse("RouterUser=admin\nRouterPass=secreta\n")
    assert r.program.network.router_user == "admin"
    assert r.program.network.router_pass == "secreta"
    assert not r.diagnostics


def test_router_pass_se_trunca_a_31_caracteres():
    """char[32] en el firmware."""
    r = parse("RouterPass=" + "x" * 40 + "\n")
    assert len(r.program.network.router_pass) == 31


def test_modem_actualiza_la_variable_sin_consumir_canal():
    r = analyze("Public Senal\nModemRSSI(Senal)\n")
    v = r.program.find_var("Senal")
    assert v.modem_field == "MODEMRSSI"
    assert v.pin == -1                      # no ocupa canal analógico
    assert "var-sin-valor" not in codigos(r)  # sí recibe valor, del poll


def test_modem_con_variable_no_declarada():
    r = parse("ModemSINR(NoExiste)\n")
    assert "fw-modem-var" in codigos(r)
