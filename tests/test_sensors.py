"""Pruebas del asistente de sensores.

La escala tiene que cerrar contra la conversión real del firmware, no
contra la fórmula de un manual: lo que importa es qué número va a reportar
el equipo, no qué número debería reportar.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic import analyze  # noqa: E402
from optabasic.sensors import (  # noqa: E402
    ERROR,
    SHUNT_NOMINAL,
    TASA_MAX_HZ,
    VREF,
    calcular_4_20,
    calcular_pulsos,
)


def niveles(escala):
    return {n for n, _ in escala.avisos}


def codigos(resultado):
    return {d.code for d in resultado.diagnostics}


# ── Modelo de lo que hace el firmware, para verificar contra él ──────────
def ma_que_reporta_el_equipo(corriente_real_ma: float, shunt: float) -> float:
    """read_mA(): el firmware divide siempre por los 270 Ω que tiene fijos."""
    volts = corriente_real_ma * shunt / 1000.0
    return (volts / SHUNT_NOMINAL) * 1000.0


def mv_que_reporta_el_equipo(corriente_real_ma: float, shunt: float) -> float:
    """VoltSE escala sobre milivolts: volts * 1000 * Mult + Offset."""
    return corriente_real_ma * shunt


# ── 4-20 mA con la resistencia que el firmware asume ─────────────────────
def test_escala_clasica_coincide_con_el_ejemplo_del_firmware():
    """El sensor de programa_compuerta.CR1: 30-500 cm sobre 270 Ω."""
    e = calcular_4_20("Dist", 30.0, 500.0, "cm", shunt=270.0)
    assert e.mult == pytest.approx(29.375)
    assert e.offset == pytest.approx(-87.5)


@pytest.mark.parametrize("shunt", [270.0, 250.0, 220.0, 150.0, 100.0])
def test_modo_ma_devuelve_el_valor_correcto_con_cualquier_resistencia(shunt):
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=shunt)
    for corriente, esperado in ((4.0, 0.0), (12.0, 2.5), (20.0, 5.0)):
        leido = ma_que_reporta_el_equipo(corriente, shunt)
        assert leido * e.mult + e.offset == pytest.approx(esperado, abs=1e-9)


@pytest.mark.parametrize("shunt", [270.0, 250.0, 100.0])
def test_modo_voltse_devuelve_el_valor_correcto(shunt):
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=shunt, modo="voltse")
    for corriente, esperado in ((4.0, 0.0), (12.0, 2.5), (20.0, 5.0)):
        mv = mv_que_reporta_el_equipo(corriente, shunt)
        assert mv * e.mult + e.offset == pytest.approx(esperado, abs=1e-9)


def test_rango_de_corriente_no_estandar():
    """Un sensor de 0-20 mA, no de 4-20."""
    e = calcular_4_20("Q", 0.0, 100.0, "l/s", i_min=0.0, i_max=20.0)
    assert e.offset == pytest.approx(0.0)
    assert ma_que_reporta_el_equipo(20.0, 270.0) * e.mult + e.offset == pytest.approx(100.0)


def test_resistencia_distinta_avisa_del_shunt_fijo():
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=250.0)
    assert any("270" in t for _, t in e.avisos)


def test_resistencia_nominal_no_molesta_con_ese_aviso():
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=270.0)
    assert not any("no va a mostrar los miliamperes reales" in t for _, t in e.avisos)


def test_resistencia_grande_satura_la_entrada():
    """A 20 mA sobre 600 Ω son 12 V y la entrada llega a 10,70 V."""
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=600.0)
    assert ERROR in niveles(e)
    assert e.hay_errores


def test_el_limite_de_saturacion_esta_donde_corresponde():
    justo = VREF * 1000.0 / 20.0            # 535 Ω exactos
    assert ERROR not in niveles(calcular_4_20("N", 0, 5, "m", shunt=justo - 5))
    assert ERROR in niveles(calcular_4_20("N", 0, 5, "m", shunt=justo + 5))


def test_resistencia_chica_avisa_de_poca_resolucion():
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=10.0)
    assert any("pasos de ADC" in t for _, t in e.avisos)


def test_rango_de_corriente_invertido_es_error():
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", i_min=20.0, i_max=4.0)
    assert e.hay_errores


# ── El código generado tiene que pasar el propio linter ──────────────────
def test_el_codigo_generado_no_tiene_errores():
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", canal=1)
    programa = (
        "StationName=Prueba\nServerHost=x.com\nServerPort=6786\nPakBusAddress=1\n"
        "Scan(10, Sec, 0, 0)\n" + e.codigo +
        "\nDataTable(T, True, 1000)\nDataInterval(0, 1, Min, 0)\n"
        "Sample(1, Nivel, FP2)\nEndTable\n"
    )
    r = analyze(programa)
    errores = [d for d in r.diagnostics if d.severity.value == "error"]
    assert not errores, [d.message for d in errores]


def test_el_codigo_generado_conserva_el_canal_del_sensor():
    """La variable en mA no debe ser destino de ninguna asignación."""
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", canal=3)
    r = analyze("Scan(10,Sec)\n" + e.codigo +
                "\nDataTable(T,True,1)\nDataInterval(0,1,Min,0)\n"
                "Sample(1,Nivel,FP2)\nEndTable\n")
    assert r.program.find_var("Nivel_mA").pin == 2      # I3 → A2
    assert "units-ma-sin-canal" not in codigos(r)


def test_el_codigo_de_voltse_tambien_pasa_el_linter():
    e = calcular_4_20("Presion", 0.0, 10.0, "bar", shunt=250.0, modo="voltse")
    r = analyze("Scan(10,Sec)\n" + e.codigo +
                "\nDataTable(T,True,1)\nDataInterval(0,1,Min,0)\n"
                "Sample(1,Presion,FP2)\nEndTable\n")
    errores = [d for d in r.diagnostics if d.severity.value == "error"]
    assert not errores, [d.message for d in errores]


def test_umbrales_de_falla_escalados_por_la_resistencia():
    """Con 250 Ω, 3,5 mA reales se ven como 3,24 en la variable."""
    e = calcular_4_20("Nivel", 0.0, 5.0, "m", shunt=250.0)
    esperado = 3.5 * 250.0 / SHUNT_NOMINAL
    assert f"{esperado:.3f}"[:4] in e.codigo


# ── Contadores de pulsos ─────────────────────────────────────────────────
def test_pluviometro_por_pulso():
    e = calcular_pulsos("Lluvia_mm", unidad_por_pulso=0.2, unidad="mm")
    assert e.mult == pytest.approx(0.2)
    assert e.offset == 0.0
    assert not e.hay_errores


def test_caudalimetro_por_unidad():
    e = calcular_pulsos("Caudal", unidad_por_pulso=450.0, unidad="l",
                        modo="por_unidad")
    assert e.mult == pytest.approx(1.0 / 450.0)


def test_caudal_alto_supera_el_antirrebote():
    """450 pulsos/litro a 30 l/min son 225 Hz, muy por encima de los 20."""
    e = calcular_pulsos("Caudal", unidad_por_pulso=450.0, unidad="l",
                        modo="por_unidad", caudal_max=30.0)
    assert e.hay_errores
    assert any("antirrebote" in t for _, t in e.avisos)


def test_caudal_dentro_del_alcance():
    e = calcular_pulsos("Caudal", unidad_por_pulso=10.0, unidad="l",
                        modo="por_unidad", caudal_max=60.0)   # 10 Hz
    assert not e.hay_errores


def test_el_tope_declarado_es_el_del_firmware():
    """50 ms de antirrebote → 20 pulsos por segundo."""
    assert TASA_MAX_HZ == 20.0
    e = calcular_pulsos("Lluvia_mm", unidad_por_pulso=0.2, unidad="mm")
    assert any("20" in v for _, v in e.datos)


def test_el_offset_de_pulsos_siempre_es_cero():
    """Se suma en cada scan: cualquier otro valor inventa un acumulado."""
    e = calcular_pulsos("Lluvia_mm", unidad_por_pulso=0.2, unidad="mm")
    assert e.offset == 0.0
    assert ", 0.0)" in e.codigo


def test_avisa_de_totalize_y_del_pull_up():
    e = calcular_pulsos("Lluvia_mm", unidad_por_pulso=0.2, unidad="mm")
    textos = " ".join(t for _, t in e.avisos)
    assert "Totalize" in textos
    assert "10 kΩ" in textos


def test_el_codigo_de_pulsos_pasa_el_linter():
    e = calcular_pulsos("Lluvia_mm", canal=1, unidad_por_pulso=0.2, unidad="mm")
    r = analyze("Scan(10,Sec)\n" + e.codigo +
                "\nDataTable(T,True,1000)\nDataInterval(0,1,Min,0)\n"
                "Totalize(1, Lluvia_mm, FP2)\nEndTable\n")
    errores = [d for d in r.diagnostics if d.severity.value == "error"]
    assert not errores, [d.message for d in errores]


def test_valor_por_pulso_invalido():
    assert calcular_pulsos("X", unidad_por_pulso=0.0).hay_errores


# ── La regla de colisión distingue lo deliberado de lo accidental ────────
def test_dos_canales_explicitos_no_son_error():
    fuente = ("Public A\nPublic B\nUnits A = mA\nUnits B = mA\n"
              "AIChannel(A, 1)\nAIChannel(B, 1)\n")
    r = analyze(fuente)
    assert "colision-canal" not in codigos(r)
    assert "canal-compartido" in codigos(r)


def test_automatico_encima_de_explicito_si_es_error():
    fuente = ("Public Temp\nPublic Caudal\nUnits Caudal = mA\n"
              "VoltSE(Temp, 1, mV5000, 1, 0, 0, 1.0, 0.0)\n")
    assert "colision-canal" in codigos(analyze(fuente))


def test_pulsos_y_analogico_en_el_mismo_borne_es_error():
    fuente = ("Public Lluvia\nPublic Nivel\nUnits Nivel = mA\n"
              "AIChannel(Nivel, 1)\nPulseCount(Lluvia, 1, P1, 2, 0, 0.2, 0.0)\n")
    r = analyze(fuente)
    assert "colision-canal" in codigos(r)
    assert any("pulsos" in d.message for d in r.diagnostics
               if d.code == "colision-canal")
