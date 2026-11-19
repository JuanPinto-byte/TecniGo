"""
Pasarela de pago en modo SANDBOX (FN-17).

No mueve dinero ni sale a internet: imita lo que hace una pasarela real
(Wompi, ePayco, Mercado Pago) en su ambiente de pruebas, donde ciertos
números de tarjeta dan siempre un resultado conocido. Para pasar a una
pasarela real solo habría que reemplazar `procesar()`.

Los datos sensibles (número de tarjeta, CVV) llegan aquí y mueren aquí:
el resto del sistema solo guarda la referencia que devuelve la pasarela.
"""
import uuid
from dataclasses import dataclass

RECHAZADO = "rechazado"
FONDOS_INSUFICIENTES = "fondos_insuficientes"
TIMEOUT = "timeout"

# Mensaje específico para el cliente según el motivo del fallo.
MENSAJES_FALLO = {
    RECHAZADO: "Tu pago fue rechazado por la entidad emisora. Revisa los datos o prueba con otro medio.",
    FONDOS_INSUFICIENTES: "Fondos insuficientes para completar el pago. Prueba con otro medio.",
    TIMEOUT: "La pasarela no respondió a tiempo. No se hizo ningún cobro; puedes reintentar.",
}

# Tarjetas de prueba del sandbox (todas válidas por Luhn).
TARJETAS_DE_PRUEBA = {
    "4000000000000002": RECHAZADO,
    "4000000000009995": FONDOS_INSUFICIENTES,
    "4000000000000119": TIMEOUT,
}


@dataclass(frozen=True)
class Resultado:
    aprobado: bool
    referencia: str = ""
    codigo: str = ""

    @property
    def motivo(self):
        return MENSAJES_FALLO.get(self.codigo, "")


def _aprobar():
    return Resultado(True, referencia="SBX-" + uuid.uuid4().hex[:12].upper())


def procesar(medio, monto, datos):
    """Devuelve el resultado simulado de cobrar `monto` con el medio indicado."""
    if medio == "tarjeta":
        codigo = TARJETAS_DE_PRUEBA.get(datos.get("numero", ""))
    elif medio == "pse":
        codigo = RECHAZADO if datos.get("banco") == "rechazado" else None
    elif medio == "billetera":
        codigo = FONDOS_INSUFICIENTES if datos.get("celular", "").endswith("0000") else None
    else:
        codigo = RECHAZADO
    if codigo:
        return Resultado(False, codigo=codigo)
    return _aprobar()
