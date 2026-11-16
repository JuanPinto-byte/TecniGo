"""Datos reales del usuario autenticado para el encabezado (campana FN-19 y dirección)."""
from core.models import Notificacion, Usuario


def datos_encabezado(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    ctx = {"n_notif": Notificacion.objects.filter(usuario=usuario, leida=False).count()}
    if usuario.rol == Usuario.Rol.CLIENTE:
        ctx["cliente"] = {"nombre": usuario.nombre_completo, "direccion": usuario.direccion}
    return ctx
