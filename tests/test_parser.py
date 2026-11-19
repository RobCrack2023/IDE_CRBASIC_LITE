"""Pruebas de fidelidad del port contra el comportamiento del firmware.

Cada caso está anclado a una línea concreta de OptaPakBus.ino. Si el
firmware cambia, estas pruebas son las que tienen que fallar primero.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic import analyze, parse  # noqa: E402
from optabasic import limits as L  # noqa: E402
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


# ── Reloj del programa en hora local (v1.7.8) ───────────────────────────

def test_utcoffset_admite_decimales():
    r = parse("UTCOffset=5.5\n")
    assert r.program.network.utc_offset == 5.5
    assert not r.diagnostics


def test_utcoffset_fuera_de_rango():
    r = parse("UTCOffset=-25\n")
    assert "fw-utcoffset-rango" in codigos(r)
    assert r.program.network.utc_offset is None


def test_clock_refresca_la_variable_sin_consumir_canal():
    r = analyze("UTCOffset=-3\nPublic Fecha\nClockYYMMDD(Fecha)\n")
    v = r.program.find_var("Fecha")
    assert v.clock_field == "CLOCKYYMMDD"
    assert v.pin == -1                        # no ocupa canal analógico
    assert "var-sin-valor" not in codigos(r)  # la refresca el firmware


def test_clock_con_variable_no_declarada():
    assert "fw-clock-var" in codigos(parse("ClockHHMM(NoExiste)\n"))


def test_reloj_sin_utcoffset_avisa():
    """Sin zona horaria devuelve UTC: una comparación horaria sale corrida."""
    r = analyze("Public Hora\nClockHHMM(Hora)\n")
    assert "reloj-sin-utcoffset" in codigos(r)


# ── PreserveVariables (v1.8.0) ──────────────────────────────────────────


def _prog(*lineas):
    """Un .CR1 minimo: sin DataTable el firmware no ejecutaria nada."""
    cuerpo = list(lineas) + [
        "DataTable(R, True, 100)",
        "    Sample(1, Consigna, FP2)",
        "EndTable",
    ]
    return chr(10).join(cuerpo) + chr(10)


def test_preserve_marca_las_variables_nombradas():
    r = parse(_prog("Public Consigna, Banda",
                    "PreserveVariables Consigna, Banda"))
    assert [v.name for v in r.program.vars if v.preserve] == ["Consigna", "Banda"]
    assert r.program.preserve_enabled
    assert not r.program.preserve_all


def test_preserve_sin_argumentos_es_la_forma_del_cr1000():
    """Preserva toda variable que escriba la plataforma, no una lista."""
    r = parse(_prog("Public Consigna", "PreserveVariables"))
    assert r.program.preserve_all
    assert r.program.preserve_enabled
    assert [v.name for v in r.program.vars if v.preserve] == []


def test_preserve_da_igual_el_orden_respecto_de_public():
    """El firmware liga los nombres al terminar el parseo."""
    r = parse(_prog("PreserveVariables Consigna", "Public Consigna"))
    assert [v.name for v in r.program.vars if v.preserve] == ["Consigna"]


def test_preserve_rechaza_una_variable_de_hardware():
    """Un canal 4-20mA se relee del sensor al arrancar: preservarlo no sirve."""
    r = parse(_prog("Public Consigna, Nivel_mA",
                    "AIChannel(Nivel_mA, 1)",
                    "PreserveVariables Consigna, Nivel_mA"))
    assert [v.name for v in r.program.vars if v.preserve] == ["Consigna"]
    assert "preserve-de-hardware" in codigos(r)


def test_preserve_con_variable_no_declarada():
    r = parse(_prog("Public Consigna", "PreserveVariables Consigna, NoExiste"))
    assert "preserve-no-declarada" in codigos(r)
    assert [v.name for v in r.program.vars if v.preserve] == ["Consigna"]


def test_preserve_topea_en_el_maximo_de_variables():
    """El tope son los 64 de CR_MAX_VARS: no cabe mas de lo declarable."""
    nombres = ["V%d" % i for i in range(L.MAX_PRESERVE + 6)]
    lineas = ["PreserveVariables " + ", ".join(nombres[i:i + 10])
              for i in range(0, len(nombres), 10)]
    r = parse(_prog("Public Consigna", *lineas))
    assert len(r.program.preserve_names) == L.MAX_PRESERVE
    assert "preserve-limite" in codigos(r)


def test_preserve_en_varias_lineas_se_acumula():
    """La agenda de Colchagua son ~38 nombres y no caben en los 127 caracteres
    de una linea: el firmware no reinicia la cuenta, las lineas suman."""
    r = parse(_prog("Public P1_Fecha, P1_Hora, P1_Cm, P2_Fecha, P2_Hora, P2_Cm",
                    "PreserveVariables P1_Fecha, P1_Hora, P1_Cm",
                    "PreserveVariables P2_Fecha, P2_Hora, P2_Cm"))
    esperados = ["P1_Fecha", "P1_Hora", "P1_Cm", "P2_Fecha", "P2_Hora", "P2_Cm"]
    assert list(r.program.preserve_names) == esperados
    assert [v.name for v in r.program.vars if v.preserve] == esperados


def test_preserve_avisa_si_el_programa_calcula_el_valor():
    """El volcado lo dispara la plataforma, no el scan."""
    r = analyze(_prog("Public Consigna, Calculada",
                      "PreserveVariables Calculada",
                      "BeginProg",
                      "    Scan(1, Sec, 0, 0)",
                      "        Calculada = Consigna * 2.0",
                      "        CallTable R",
                      "    NextScan",
                      "EndProg"))
    assert "preserve-calculada" in codigos(r)


def test_preserve_sin_lista_sugiere_nombrar_las_consignas():
    r = analyze(_prog("Public Consigna", "PreserveVariables"))
    assert "preserve-sin-lista" in codigos(r)


# ── MedianRun (v1.9.0) ──────────────────────────────────────────────────


def _med(*lineas):
    cuerpo = ["Public Nivel_mA, Nivel_filt",
              "Units Nivel_mA = mA",
              "AIChannel(Nivel_mA, 1)"] + list(lineas) + [
        "DataTable(R, True, 100)",
        "    Sample(1, Nivel_filt, FP2)",
        "EndTable",
    ]
    return chr(10).join(cuerpo) + chr(10)


def test_medianrun_declara_el_filtro():
    r = parse(_med("MedianRun(Nivel_filt, Nivel_mA, 7)"))
    assert len(r.program.medians) == 1
    m = r.program.medians[0]
    assert (m.dest, m.src, m.window) == ("Nivel_filt", "Nivel_mA", 7)
    assert r.program.find_var("Nivel_filt").is_median


def test_medianrun_el_destino_no_consume_canal():
    """Lo calcula el filtro, no un borne: no entra al reparto de A0-A7."""
    r = parse(_med("MedianRun(Nivel_filt, Nivel_mA, 5)"))
    assert r.program.find_var("Nivel_filt").pin == -1


def test_medianrun_preservevariables_rechaza_el_destino():
    """El equipo lo recalcula en cada scan, asi que preservarlo no sirve.

    El nombre viejo decia "cuenta como de hardware", que es justo la nocion
    conflacionada: el destino de un filtro no sale de ningun borne — el test
    de al lado verifica que no toma pin — y lo que se comprueba aca es la
    decision de preservacion, no de donde sale el valor.
    """
    assert parse(_med("MedianRun(Nivel_filt, Nivel_mA, 5)")
                 ).program.find_var("Nivel_filt").preserve_pointless


def test_medianrun_ventana_par_baja_a_la_impar_anterior():
    r = parse(_med("MedianRun(Nivel_filt, Nivel_mA, 8)"))
    assert r.program.medians[0].window == 7
    assert "medianrun-ventana-par" in codigos(r)


def test_medianrun_ventana_fuera_de_rango_se_topea():
    r = parse(_med("MedianRun(Nivel_filt, Nivel_mA, 20)"))
    assert r.program.medians[0].window == L.MEDIAN_MAX_WIN
    assert "medianrun-ventana" in codigos(r)


def test_medianrun_rechaza_filtrar_sobre_si_misma():
    """Realimentaria el filtro con su propia salida."""
    r = parse(_med("MedianRun(Nivel_mA, Nivel_mA, 5)"))
    assert r.program.medians == []
    assert "medianrun-misma-variable" in codigos(r)


def test_medianrun_topea_en_cuatro_filtros():
    lineas = ["Public a, b, c, d, e, f, g, h"]
    lineas += ["MedianRun(%s, %s, 5)" % (x, y)
               for x, y in (("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"))]
    lineas.append("MedianRun(Nivel_filt, Nivel_mA, 5)")
    r = parse(_med(*lineas))
    assert len(r.program.medians) == L.MAX_MEDIAN
    assert "medianrun-limite" in codigos(r)


def test_medianrun_destino_tambien_asignado_es_error():
    """El filtro corre antes que los statements: la asignacion lo pisa."""
    r = analyze(_med("MedianRun(Nivel_filt, Nivel_mA, 5)",
                     "BeginProg",
                     "    Scan(1, Sec, 0, 0)",
                     "        Nivel_filt = Nivel_mA * 2.0",
                     "        CallTable R",
                     "    NextScan",
                     "EndProg"))
    assert "mediana-destino-asignado" in codigos(r)


def test_medianrun_argumentos_al_reves_avisa():
    r = analyze(_med("MedianRun(Nivel_mA, Nivel_filt, 5)"))
    assert "mediana-fuente-sin-lectura" in codigos(r)


def test_el_destino_de_una_mediana_no_es_variable_muerta():
    """Lo escribe el filtro en cada scan, antes de los statements.

    Lo encontro el programa de banco: el aviso decia que Nivel_filt "va a
    valer 0 siempre", que es justo lo contrario de lo que pasa.
    """
    r = analyze(_med("MedianRun(Nivel_filt, Nivel_mA, 5)"))
    muertas = [d.line for d in r.diagnostics if d.code == "variable-muerta"]
    assert muertas == []


# ── SetpointSchedule (v1.9.3) ───────────────────────────────────────────


def _sch(*lineas):
    cuerpo = ["Public Consigna_cm, Consigna2_cm, Agenda_N, Agenda_Serie, Otra"] + list(lineas) + [
        "DataTable(R, True, 100)",
        "    Sample(1, Consigna_cm, FP2)",
        "EndTable",
    ]
    return chr(10).join(cuerpo) + chr(10)


def test_setpointschedule_declara_la_agenda():
    r = parse(_sch("SetpointSchedule(Consigna_cm, 1, Agenda_N, Agenda_Serie)"))
    assert len(r.program.schedules) == 1
    s = r.program.schedules[0]
    assert (s.dest, s.canal, s.n_var, s.serie_var) == (
        "Consigna_cm", 1, "Agenda_N", "Agenda_Serie")
    assert r.program.find_var("Consigna_cm").is_scheduled
    assert r.program.find_var("Agenda_N").is_sched_info
    assert r.program.find_var("Agenda_Serie").is_sched_info


def test_setpointschedule_los_dos_ultimos_argumentos_son_opcionales():
    r = parse(_sch("SetpointSchedule(Consigna_cm, 2)"))
    assert [s.canal for s in r.program.schedules] == [2]
    assert not r.program.find_var("Agenda_N").is_sched_info


def test_setpointschedule_el_canal_puede_ser_una_const():
    r = parse(_sch("Const Compuerta = 2",
                   "SetpointSchedule(Consigna_cm, Compuerta)"))
    assert r.program.schedules[0].canal == 2


def test_setpointschedule_canal_fuera_de_rango_o_variable_se_rechaza():
    for canal in ("0", "5", "1.5", "Otra", "Inexistente"):
        r = parse(_sch("SetpointSchedule(Consigna_cm, %s)" % canal))
        assert r.program.schedules == [], canal
        assert "setpoint-canal" in codigos(r), canal


def test_setpointschedule_consigna_no_declarada():
    r = parse(_sch("SetpointSchedule(Fantasma, 1)"))
    assert r.program.schedules == []
    assert "setpoint-no-declarada" in codigos(r)


def test_setpointschedule_dos_compuertas_dos_instrucciones():
    r = parse(_sch("SetpointSchedule(Consigna_cm, 1)",
                   "SetpointSchedule(Consigna2_cm, 2)"))
    assert [(s.dest, s.canal) for s in r.program.schedules] == [
        ("Consigna_cm", 1), ("Consigna2_cm", 2)]


def test_setpointschedule_rechaza_canal_o_consigna_repetidos():
    r = parse(_sch("SetpointSchedule(Consigna_cm, 1)",
                   "SetpointSchedule(Consigna2_cm, 1)"))
    assert len(r.program.schedules) == 1
    assert "setpoint-canal-repetido" in codigos(r)
    r = parse(_sch("SetpointSchedule(Consigna_cm, 1)",
                   "SetpointSchedule(Consigna_cm, 2)"))
    assert len(r.program.schedules) == 1
    assert "setpoint-consigna-repetida" in codigos(r)


def test_setpointschedule_rechaza_una_consigna_que_ya_maneja_otra_cosa():
    """Si ya la escribe un filtro, la agenda y el filtro se pisarian."""
    r = parse(_sch("MedianRun(Consigna_cm, Otra, 5)",
                   "SetpointSchedule(Consigna_cm, 1)"))
    assert r.program.schedules == []
    assert "setpoint-consigna-ocupada" in codigos(r)


def test_setpointschedule_tope_de_instrucciones():
    lineas = ["Public a, b, c, d, e"]
    lineas += ["SetpointSchedule(%s, %d)" % (v, i + 1)
               for i, v in enumerate("abcd")]
    lineas.append("SetpointSchedule(e, 1)")
    r = parse(_sch(*lineas))
    assert len(r.program.schedules) == L.MAX_SCHED
    assert "setpoint-limite" in codigos(r)


# El corazon del diseño: dos preguntas, dos predicados. La consigna de una
# agenda NO es inutil de preservar (en modo degradado el equipo no le escribe,
# asi que su ultimo valor tiene que sobrevivir un reinicio), pero SI esta
# escrita por el equipo (no es variable muerta).


def test_la_consigna_de_una_agenda_es_preservable():
    r = parse(_sch("PreserveVariables Consigna_cm",
                   "SetpointSchedule(Consigna_cm, 1)"))
    v = r.program.find_var("Consigna_cm")
    assert v.preserve
    assert not v.preserve_pointless
    assert "preserve-de-hardware" not in codigos(r)


def test_la_consigna_de_una_agenda_esta_escrita_por_el_equipo():
    v = parse(_sch("SetpointSchedule(Consigna_cm, 1)")).program.find_var("Consigna_cm")
    assert v.is_written and not v.preserve_pointless


def test_agenda_n_y_serie_son_inutiles_de_preservar():
    """Salen del archivo en cada scan: preservarlas devolveria un valor viejo."""
    r = parse(_sch("PreserveVariables Agenda_N",
                   "SetpointSchedule(Consigna_cm, 1, Agenda_N, Agenda_Serie)"))
    assert r.program.find_var("Agenda_N").preserve_pointless
    assert "preserve-de-hardware" in codigos(r)


def test_preserve_pointless_es_subconjunto_de_is_written():
    """El invariante que ordena los dos predicados."""
    r = parse(_sch("Public Bat, Reloj",
                   "Battery(Bat, 8)",
                   "ClockHHMM(Reloj)",
                   "MedianRun(Otra, Bat, 5)",
                   "SetpointSchedule(Consigna_cm, 1, Agenda_N, Agenda_Serie)"))
    for v in r.program.vars:
        if v.preserve_pointless:
            assert v.is_written, v.name
    # y el unico que difiere es la consigna de la agenda
    solo = [v.name for v in r.program.vars
            if v.is_written and not v.preserve_pointless]
    assert solo == ["Consigna_cm"]


def test_la_consigna_de_una_agenda_no_es_variable_muerta():
    r = analyze(_sch("PreserveVariables Consigna_cm",
                     "SetpointSchedule(Consigna_cm, 1, Agenda_N, Agenda_Serie)"))
    muertas = {d.fragment for d in r.diagnostics if d.code == "variable-muerta"}
    assert not any("Consigna_cm" in m or "Agenda_" in m for m in muertas)
    nombres = [d.message for d in r.diagnostics if d.code == "variable-muerta"]
    assert not any("Consigna_cm" in m or "Agenda_N" in m for m in nombres)


def test_filtrar_la_consigna_de_una_agenda_no_avisa_falso_positivo():
    """MedianRun(Suavizada, Consigna_cm, 5): la trampa de lint:103."""
    r = analyze(_sch("Public Suavizada",
                     "PreserveVariables Consigna_cm",
                     "SetpointSchedule(Consigna_cm, 1)",
                     "MedianRun(Suavizada, Consigna_cm, 5)"))
    assert "mediana-fuente-sin-lectura" not in codigos(r)


def test_agenda_sin_preserve_avisa():
    r = analyze(_sch("SetpointSchedule(Consigna_cm, 1)"))
    assert "agenda-sin-preserve" in codigos(r)


def test_agenda_con_preserve_sin_lista_no_avisa():
    """La forma sin argumentos tambien la cubre."""
    r = analyze(_sch("PreserveVariables", "SetpointSchedule(Consigna_cm, 1)"))
    assert "agenda-sin-preserve" not in codigos(r)


def test_agenda_con_consigna_asignada_por_el_programa_avisa():
    r = analyze(_sch("PreserveVariables Consigna_cm",
                     "SetpointSchedule(Consigna_cm, 1)",
                     "BeginProg",
                     "    Scan(1, Sec, 0, 0)",
                     "        Consigna_cm = 40",
                     "        CallTable R",
                     "    NextScan",
                     "EndProg"))
    assert "agenda-consigna-asignada" in codigos(r)


def test_la_instruccion_esta_en_el_catalogo():
    from optabasic.reference import buscar
    ficha = buscar("SetpointSchedule")
    assert ficha is not None
    assert len(ficha.parametros) == len(ficha.firma_partes()) == 5
    assert [p.opcional for p in ficha.parametros] == [False, False, True, True, True]


# ── ModbusRTU (v1.10.0) ─────────────────────────────────────────────────
def _mb(*lineas, vars_=None):
    """Un .CR1 con los datos de una estacion y la lectura que se le pida."""
    decl = vars_ or ["Public Res", "Public Viento, Dir, Temp, Hum, Pres", "Public Otra"]
    cuerpo = decl + list(lineas) + [
        "DataTable(R, True, 100)",
        "    Sample(1, Viento, FP2)",
        "EndTable",
    ]
    return chr(10).join(cuerpo) + chr(10)


_LECTURA = "ModbusRTU(Res, Viento, 1, 3, 0, 5, 0, 10)"


def test_modbusrtu_declara_la_lectura():
    r = parse(_mb(_LECTURA))
    assert r.program.modbus and len(r.program.modbus) == 1
    m = r.program.modbus[0]
    assert (m.result, m.first, m.slave, m.fn, m.start, m.count, m.type) == (
        "Res", "Viento", 1, 3, 0, 5, 0)
    assert m.interval_s == 10 and m.mult == 1.0 and m.offset == 0.0
    assert not [d for d in r.diagnostics if d.code.startswith("modbus")]


def test_modbusrtu_marca_resultado_y_las_n_variables_consecutivas():
    r = parse(_mb(_LECTURA))
    marcadas = [v.name for v in r.program.vars if v.is_modbus]
    assert marcadas == ["Res", "Viento", "Dir", "Temp", "Hum", "Pres"]
    assert not r.program.find_var("Otra").is_modbus
    assert all(v.no_auto_pin for v in r.program.vars if v.is_modbus)


def test_modbusrtu_las_variables_del_bus_no_se_preservan():
    """preserve_pointless: el equipo las recalcula, preservarlas daria un dato viejo."""
    r = parse(_mb(_LECTURA))
    assert r.program.find_var("Viento").preserve_pointless
    assert not r.program.find_var("Otra").preserve_pointless


def test_modbusrtu_acepta_mult_y_offset():
    r = parse(_mb("ModbusRTU(Res, Viento, 1, 3, 0, 5, 2, 10, 0.1, -5)"))
    m = r.program.modbus[0]
    assert (m.type, m.mult, m.offset) == (2, 0.1, -5.0)


def test_modbusrtu_acepta_constantes_en_los_argumentos():
    r = parse(_mb("Const Esc = 7", "Const Cuantos = 5",
                  "ModbusRTU(Res, Viento, Esc, 3, 0, Cuantos, 0, 10)"))
    assert r.program.modbus and r.program.modbus[0].slave == 7


@pytest.mark.parametrize("linea,codigo", [
    ("ModbusRTU(Res, Viento, 1, 3, 0, 5, 0)", "modbus-argumentos"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 5, 0, 10, 1, 0, 9)", "modbus-argumentos"),
    ("ModbusRTU(Nada, Viento, 1, 3, 0, 5, 0, 10)", "modbus-no-declarada"),
    ("ModbusRTU(Res, Viento, Dir, 3, 0, 5, 0, 10)", "modbus-no-constante"),
    ("ModbusRTU(Res, Viento, 0, 3, 0, 5, 0, 10)", "modbus-esclavo"),
    ("ModbusRTU(Res, Viento, 248, 3, 0, 5, 0, 10)", "modbus-esclavo"),
    ("ModbusRTU(Res, Viento, 1, 5, 0, 5, 0, 10)", "modbus-funcion"),
    ("ModbusRTU(Res, Viento, 1, 3, 70000, 5, 0, 10)", "modbus-inicio"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 0, 0, 10)", "modbus-cantidad"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 33, 0, 10)", "modbus-cantidad"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 5, 8, 10)", "modbus-tipo"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 5, 0, 0)", "modbus-intervalo"),
    ("ModbusRTU(Res, Viento, 1, 3, 0, 5, 0, 10, 0)", "modbus-mult"),
    ("ModbusRTU(Res, Pres, 1, 3, 0, 3, 0, 10)", "modbus-sin-variables"),
    ("ModbusRTU(Dir, Viento, 1, 3, 0, 5, 0, 10)", "modbus-resultado-dentro"),
])
def test_modbusrtu_rechaza_lo_que_el_firmware_rechaza(linea, codigo):
    r = parse(_mb(linea))
    assert codigo in codigos(r)
    assert not r.program.modbus


def test_modbusrtu_dos_lecturas_no_pueden_compartir_variables():
    r = parse(_mb(_LECTURA, "ModbusRTU(Otra, Temp, 2, 3, 0, 2, 0, 10)"))
    assert len(r.program.modbus) == 1
    assert "modbus-variable-ocupada" in codigos(r)


def test_modbusrtu_dos_lecturas_distintas_conviven():
    r = parse(_mb("ModbusRTU(Res, Viento, 1, 3, 0, 3, 0, 10)",
                  "ModbusRTU(Otra, Hum, 2, 4, 0, 2, 2, 30)"))
    assert len(r.program.modbus) == 2


def test_modbusrtu_maximo_de_lecturas():
    vars_ = ["Public R1, R2, R3, R4, R5", "Public D1, D2, D3, D4, D5", "Public Viento"]
    lineas = [f"ModbusRTU(R{i}, D{i}, {i}, 3, 0, 1, 2, 10)" for i in range(1, 6)]
    r = parse(_mb(*lineas, vars_=vars_))
    assert len(r.program.modbus) == L.MAX_MODBUS
    assert "modbus-limite" in codigos(r)


def test_modbusrtu_una_consigna_de_agenda_no_puede_ser_destino():
    r = parse(_mb("PreserveVariables Viento",
                  "SetpointSchedule(Viento, 1)",
                  _LECTURA))
    assert "modbus-variable-ocupada" in codigos(r)


def test_setpointschedule_no_acepta_una_variable_del_bus():
    r = parse(_mb(_LECTURA, "SetpointSchedule(Viento, 1)"))
    assert "setpoint-consigna-ocupada" in codigos(r)


def test_registros_por_valor():
    r = parse(_mb("ModbusRTU(Res, Viento, 1, 3, 0, 3, 0, 10)",
                  "ModbusRTU(Otra, Hum, 1, 3, 0, 2, 2, 10)"))
    a, b = r.program.modbus
    assert (a.registers_per_value, b.registers_per_value) == (2, 1)
    r = parse(_mb("ModbusRTU(Res, Viento, 1, 1, 0, 5, 0, 10)"))
    assert r.program.modbus[0].registers_per_value == 1   # bobinas: un bit por valor


# -- directivas del bus
@pytest.mark.parametrize("linea,codigo", [
    ("ModbusBaud=1000", "modbus-baud"),
    ("ModbusBaud=230400", "modbus-baud"),
    ("ModbusFormato=7E1", "modbus-formato"),
    ("ModbusTimeout=10", "modbus-timeout"),
    ("ModbusTimeout=5000", "modbus-timeout"),
])
def test_directivas_modbus_fuera_de_rango(linea, codigo):
    r = parse(_mb(linea))
    assert codigo in codigos(r)


def test_directivas_modbus_validas():
    n = parse(_mb("ModbusBaud=19200", "ModbusFormato = 8e1", "ModbusTimeout=300")).program.network
    assert (n.modbus_baud, n.modbus_format, n.modbus_timeout) == (19200, "8E1", 300)


def test_directivas_modbus_sin_igual():
    r = parse(_mb("ModbusBaud"))
    assert "fw-directiva" in codigos(r)


def test_sin_directivas_el_bus_queda_por_defecto():
    n = parse(_mb(_LECTURA)).program.network
    assert (n.modbus_baud, n.modbus_format, n.modbus_timeout) == (None, None, None)


# -- lint
def test_lint_avisa_del_bus_por_defecto():
    assert "modbus-bus-por-defecto" in codigos(analyze(_mb(_LECTURA)))
    assert "modbus-bus-por-defecto" not in codigos(analyze(_mb("ModbusBaud=9600", _LECTURA)))


def test_lint_lista_las_variables_que_llena():
    r = analyze(_mb(_LECTURA))
    d = [d for d in r.diagnostics if d.code == "modbus-variables"]
    assert d and "Viento, Dir, Temp, Hum, Pres" in d[0].message


def test_lint_avisa_si_el_programa_asigna_una_variable_del_bus():
    r = analyze(_mb(_LECTURA, "BeginProg", "    Scan(1, Sec, 0, 0)",
                    "        Viento = 3", "        CallTable R", "    NextScan", "EndProg"))
    assert "modbus-variable-asignada" in codigos(r)


def test_lint_avisa_que_bloquea_los_reles():
    r = analyze(_mb(_LECTURA, "BeginProg", "    Scan(1, Sec, 0, 0)",
                    "        PortSet(1, 1)", "        CallTable R", "    NextScan", "EndProg"))
    assert "modbus-bloquea-reles" in codigos(r)


def test_lint_no_avisa_de_reles_si_no_los_hay():
    r = analyze(_mb(_LECTURA, "BeginProg", "    Scan(10, Sec, 0, 0)",
                    "        CallTable R", "    NextScan", "EndProg"))
    assert "modbus-bloquea-reles" not in codigos(r)


def test_lint_intervalo_menor_que_el_scan():
    r = analyze(_mb("ModbusRTU(Res, Viento, 1, 3, 0, 5, 0, 5)",
                    "BeginProg", "    Scan(30, Sec, 0, 0)",
                    "        CallTable R", "    NextScan", "EndProg"))
    assert "modbus-intervalo-menor-scan" in codigos(r)


def test_lint_modbusmaster_de_campbell_remite_a_modbusrtu():
    r = analyze(_mb("BeginProg", "    Scan(1, Sec, 0, 0)",
                    "        ModbusMaster(Res, 1, 9600, 1, 3, Viento, 1, 5, 3, 100, 0)",
                    "        CallTable R", "    NextScan", "EndProg"))
    assert [d for d in r.diagnostics if "ModbusRTU" in d.message]


def test_modbusrtu_esta_en_el_catalogo():
    from optabasic.reference import buscar
    ficha = buscar("ModbusRTU")
    assert ficha is not None
    assert len(ficha.parametros) == len(ficha.firma_partes()) == 10
    assert [p.opcional for p in ficha.parametros][-2:] == [True, True]
    for d in ("ModbusBaud", "ModbusFormato", "ModbusTimeout"):
        assert buscar(d) is not None


def test_la_version_del_motor_es_la_del_firmware():
    assert L.FIRMWARE_VERSION == "1.11.1"


# ── RatingCurve y Modo de SetpointSchedule (v1.11.0) ────────────────────
def _rc(*lineas):
    """Un .CR1 con un nivel, un caudal y la agenda de una compuerta."""
    cuerpo = ["Public Nivel_cm, Caudal, Consigna, Modo_C, Agenda_N, Agenda_Serie, Otra"] + list(lineas) + [
        "DataTable(R, True, 100)",
        "    Sample(1, Caudal, FP2)",
        "EndTable",
    ]
    return chr(10).join(cuerpo) + chr(10)


def test_ratingcurve_declara_la_curva():
    r = parse(_rc("AIChannel(Nivel_cm, 1)",
                  "RatingCurve(Caudal, Nivel_cm, 0.015, 1.4991)"))
    assert len(r.program.ratings) == 1
    c = r.program.ratings[0]
    assert (c.dest, c.src, c.a, c.b) == ("Caudal", "Nivel_cm", 0.015, 1.4991)
    q = r.program.find_var("Caudal")
    assert q.is_rating and q.no_auto_pin
    assert q.pin == -1                      # no consume un canal analogico


def test_ratingcurve_acepta_const_en_a_y_b():
    r = parse(_rc("Const Coef = 0.015", "Const Expo = 1.4991",
                  "RatingCurve(Caudal, Nivel_cm, Coef, Expo)"))
    c = r.program.ratings[0]
    assert (c.a, c.b) == (0.015, 1.4991)


def test_ratingcurve_rechaza_a_y_b_variables():
    r = parse(_rc("RatingCurve(Caudal, Nivel_cm, Otra, 1.5)"))
    assert r.program.ratings == []
    assert "rating-no-constante" in codigos(r)


def test_ratingcurve_rechaza_coeficientes_fuera_de_rango():
    for a, b, cod in (("0", "1.5", "rating-a"), ("-1", "1.5", "rating-a"),
                      ("2000000", "1.5", "rating-a"), ("0.015", "0.05", "rating-b"),
                      ("0.015", "6", "rating-b")):
        r = parse(_rc("RatingCurve(Caudal, Nivel_cm, %s, %s)" % (a, b)))
        assert r.program.ratings == [], (a, b)
        assert cod in codigos(r), (a, b)


def test_ratingcurve_argumentos_y_variables():
    r = parse(_rc("RatingCurve(Caudal, Nivel_cm, 0.015)"))
    assert "rating-argumentos" in codigos(r)
    r = parse(_rc("RatingCurve(Fantasma, Nivel_cm, 0.015, 1.5)"))
    assert "rating-no-declarada" in codigos(r)
    r = parse(_rc("RatingCurve(Caudal, Caudal, 0.015, 1.5)"))
    assert "rating-misma-variable" in codigos(r)


def test_ratingcurve_topea_en_cuatro_curvas():
    lineas = ["Public n, q1, q2, q3, q4, q5"]
    lineas += ["RatingCurve(%s, n, 0.015, 1.5)" % v for v in ("q1", "q2", "q3", "q4", "q5")]
    r = parse(chr(10).join(lineas) + chr(10))
    assert len(r.program.ratings) == 4
    assert "rating-limite" in codigos(r)


def test_ratingcurve_rechaza_un_caudal_que_ya_maneja_otra_cosa():
    r = parse(_rc("MedianRun(Caudal, Otra, 5)",
                  "RatingCurve(Caudal, Nivel_cm, 0.015, 1.5)"))
    assert r.program.ratings == []
    assert "rating-destino-ocupado" in codigos(r)


def test_ratingcurve_el_caudal_asignado_por_el_programa_es_error():
    r = analyze(_rc("AIChannel(Nivel_cm, 1)",
                    "RatingCurve(Caudal, Nivel_cm, 0.015, 1.5)",
                    "BeginProg",
                    "    Scan(1, Sec, 0, 0)",
                    "        Caudal = Nivel_cm * 2",
                    "        CallTable R",
                    "    NextScan",
                    "EndProg"))
    assert "rating-destino-asignado" in codigos(r)


def test_ratingcurve_nivel_sin_lectura_avisa_y_el_caudal_no_es_variable_muerta():
    r = analyze(_rc("RatingCurve(Caudal, Otra, 0.015, 1.5)"))
    assert "rating-nivel-sin-lectura" in codigos(r)
    r = analyze(_rc("AIChannel(Nivel_cm, 1)",
                    "RatingCurve(Caudal, Nivel_cm, 0.015, 1.5)"))
    assert "rating-nivel-sin-lectura" not in codigos(r)
    muertas = [d for d in r.diagnostics if d.code == "variable-muerta"]
    assert all("Caudal" not in d.message for d in muertas)


def test_ratingcurve_preservevariables_rechaza_el_caudal():
    r = parse(_rc("AIChannel(Nivel_cm, 1)",
                  "RatingCurve(Caudal, Nivel_cm, 0.015, 1.5)",
                  "PreserveVariables Caudal"))
    assert "preserve-inutil" in codigos(r) or any(
        "Caudal" in d.message for d in r.diagnostics)


def test_setpointschedule_con_modo():
    r = parse(_rc("SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C)"))
    s = r.program.schedules[0]
    assert s.modo_var == "Modo_C"
    m = r.program.find_var("Modo_C")
    assert m.is_scheduled and m.no_auto_pin
    assert not m.preserve_pointless     # se preserva igual que la consigna


def test_setpointschedule_modo_no_declarado_o_repetido():
    r = parse(_rc("SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Fantasma)"))
    assert r.program.schedules == []
    assert "setpoint-info-no-declarada" in codigos(r)
    r = parse(_rc("SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Consigna)"))
    assert r.program.schedules == []
    assert "setpoint-variables-repetidas" in codigos(r)
    r = parse(_rc("SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Agenda_N)"))
    assert r.program.schedules == []
    assert "setpoint-variables-repetidas" in codigos(r)


def test_setpointschedule_modo_ya_manejado_por_otra_instruccion():
    r = parse(_rc("MedianRun(Modo_C, Otra, 5)",
                  "SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C)"))
    assert r.program.schedules == []
    assert "setpoint-modo-ocupado" in codigos(r)


def test_setpointschedule_con_seis_argumentos_se_rechaza():
    r = parse(_rc("SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C, Otra)"))
    assert r.program.schedules == []
    assert "setpoint-argumentos" in codigos(r)


def test_modo_sin_preservevariables_avisa():
    sin = analyze(_rc("PreserveVariables Consigna",
                      "SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C)"))
    assert "agenda-modo-sin-preserve" in codigos(sin)
    con = analyze(_rc("PreserveVariables Consigna, Modo_C",
                      "SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C)"))
    assert "agenda-modo-sin-preserve" not in codigos(con)


def test_el_modo_asignado_por_el_programa_avisa():
    r = analyze(_rc("PreserveVariables Consigna, Modo_C",
                    "SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_C)",
                    "BeginProg",
                    "    Scan(1, Sec, 0, 0)",
                    "        Modo_C = 1",
                    "        CallTable R",
                    "    NextScan",
                    "EndProg"))
    assert "agenda-modo-asignado" in codigos(r)


def test_ratingcurve_esta_en_el_catalogo():
    from optabasic.reference import buscar
    ficha = buscar("RatingCurve")
    assert ficha is not None
    assert len(ficha.parametros) == len(ficha.firma_partes()) == 4
    assert [p.opcional for p in ficha.parametros] == [False, False, False, False]


def test_el_programa_de_ejemplo_en_caudal_no_tiene_errores():
    """programa_banco_caudal.CR1 (repo del firmware) es el ejemplo que se le da
    a quien programa en caudal: tiene que cargar limpio con el motor del IDE."""
    from optabasic.diagnostics import Severity
    ruta = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "proyecto_arduino", "OptaPakBus", "programa_banco_caudal.CR1")
    if not os.path.exists(ruta):
        pytest.skip("el repo del firmware no esta junto al del IDE")
    with open(ruta, encoding="ascii", newline="") as f:
        r = analyze(f.read())
    errores = [d for d in r.diagnostics if d.severity == Severity.ERROR]
    assert errores == [], [d.message for d in errores]
    assert len(r.program.ratings) == 1
    sc = r.program.schedules[0]
    assert sc.modo_var == "Modo_Consigna"
    assert len(r.program.consts) <= L.MAX_CONSTS
