from functools import wraps
import math
from mimetypes import guess_type

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.mail import send_mail
from django.http import FileResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms import PerfilClienteForm, PerfilTecnicoForm, RegistroClienteForm, SolicitudForm, RegistroTecnicoForm
from core.models import Categoria, Notificacion, PerfilTecnico, Solicitud, Usuario

from . import datos_falsos as d


def requiere_rol(rol):
    def decorador(vista):
        @wraps(vista)
        @login_required
        def protegida(request, *args, **kwargs):
            usuario = request.user
            if usuario.rol != rol:
                messages.error(request, "No tienes permiso para acceder a esta sección.")
                return redirect("login")
            if usuario.esta_suspendido:  # FN-2/FN-15: una cuenta suspendida no opera
                logout(request)
                messages.error(request, "Tu cuenta está suspendida.")
                return redirect("login")
            if rol == Usuario.Rol.TECNICO and usuario.estado != Usuario.Estado.ACTIVO:
                logout(request)
                messages.error(request, "Tu cuenta de técnico no está habilitada para operar.")
                return redirect("login")
            return vista(request, *args, **kwargs)
        return protegida
    return decorador


def _ctx(rol, **extra):
    base = {"rol": rol, "cliente": d.CLIENTE, "n_notif": 3}
    base.update(extra)
    return base


def _coordenadas_validas(latitud, longitud):
    return (
        latitud is not None and longitud is not None
        and math.isfinite(latitud) and math.isfinite(longitud)
        and -90 <= latitud <= 90 and -180 <= longitud <= 180
    )


def _datos_tarjeta_tecnico(perfil, latitud_cliente=None, longitud_cliente=None):
    usuario = perfil.usuario
    if not _coordenadas_validas(usuario.latitud, usuario.longitud):
        return None
    rating = float(perfil.calificacion_promedio) or None
    precio = int(perfil.precio_referencia) if perfil.precio_referencia is not None else None
    partes_nombre = usuario.nombre_completo.split()
    tiene_ubicacion_cliente = _coordenadas_validas(latitud_cliente, longitud_cliente)
    return {
        "id": usuario.pk,
        "nombre": usuario.nombre_completo,
        "iniciales": "".join(parte[0] for parte in partes_nombre[:2]).upper(),
        "categoria": perfil.especialidad,
        "especialidad": perfil.get_especialidad_display(),
        "zona_cobertura": perfil.zona_cobertura,
        "icono": ICONOS_CATEGORIA[perfil.especialidad],
        "rating": rating,
        "rating_txt": f"{rating:.1f}".replace(".", ",") if rating else "Sin calificaciones",
        "resenas": perfil.total_calificaciones,
        "precio": precio,
        "precio_txt": d.precio_txt(precio),
        "lat": usuario.latitud,
        "lng": usuario.longitud,
        "km": (
            d.haversine_km(latitud_cliente, longitud_cliente, usuario.latitud, usuario.longitud)
            if tiene_ubicacion_cliente else None
        ),
    }


# ---------- Público ----------
def landing(request):
    return render(request, "publico/landing.html", _ctx("publico", categorias=d.CATEGORIAS))


def login_view(request):
    if request.method == "POST":
        usuario = authenticate(
            request, username=request.POST.get("correo", "").strip(),
            password=request.POST.get("clave", ""),
        )
        if usuario is None:
            messages.error(request, "Correo o contraseña incorrectos.")
        elif usuario.estado != Usuario.Estado.ACTIVO:
            estado_mensajes = {
                Usuario.Estado.PENDIENTE_APROBACION: "Tu registro está pendiente de aprobación.",
                Usuario.Estado.RECHAZADO: "Tu registro como técnico fue rechazado.",
                Usuario.Estado.SUSPENDIDO: "Tu cuenta está suspendida.",
            }
            messages.error(request, estado_mensajes.get(usuario.estado, "La cuenta no está habilitada."))
        else:
            login(request, usuario)
            destinos = {
                Usuario.Rol.CLIENTE: "cliente_inicio",
                Usuario.Rol.TECNICO: "tecnico_solicitudes",
                Usuario.Rol.ADMINISTRADOR: "admin_tecnicos",
            }
            return redirect(destinos.get(usuario.rol, "landing"))
    return render(request, "publico/login.html", _ctx("publico"))


@require_POST
def cerrar_sesion(request):
    logout(request)
    return redirect("landing")


def registro_cliente(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)  # FN-1: autentica automáticamente tras registrarse
            return redirect("cliente_inicio")
    else:
        form = RegistroClienteForm()
    return render(request, "publico/registro_cliente.html", _ctx("publico", form=form))


def registro_tecnico(request):
    if request.method == "POST":
        form = RegistroTecnicoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            # FN-8: a diferencia del cliente, NO se loguea automáticamente:
            # queda pendiente de aprobación (FN-14).
            return render(request, "publico/registro_tecnico_ok.html", _ctx("publico"))
    else:
        form = RegistroTecnicoForm()
    return render(request, "publico/registro_tecnico.html", _ctx("publico", form=form))


# ---------- Cliente ----------
@requiere_rol(Usuario.Rol.CLIENTE)
def cliente_inicio(request):
    tiene_ubicacion = _coordenadas_validas(request.user.latitud, request.user.longitud)
    cliente = {
        "nombre": request.user.nombre_completo,
        "direccion": request.user.direccion,
        "lat": request.user.latitud if tiene_ubicacion else None,
        "lng": request.user.longitud if tiene_ubicacion else None,
        "ubicacion_disponible": tiene_ubicacion,
    }
    perfiles = PerfilTecnico.objects.select_related("usuario").filter(
        usuario__rol=Usuario.Rol.TECNICO,
        usuario__estado=Usuario.Estado.ACTIVO,
        disponible=True,
    )
    tecnicos = []
    if tiene_ubicacion:
        for perfil in perfiles:
            datos = _datos_tarjeta_tecnico(perfil, cliente["lat"], cliente["lng"])
            if datos is not None:
                tecnicos.append(datos)
    tecnicos.sort(key=lambda tecnico: tecnico["km"])
    return render(request, "cliente/inicio.html", _ctx(
        "cliente", categorias=d.CATEGORIAS, en_curso=d.SOLICITUD_EN_CURSO,
        tecnicos=tecnicos[:4], cliente=cliente))


@requiere_rol(Usuario.Rol.CLIENTE)
def solicitud_nueva(request):
    """FN-3: crea la solicitud (pendiente) y la difunde a los técnicos de la categoría."""
    if not request.user.direccion.strip():
        messages.warning(request, "Registra tu dirección en tu perfil antes de crear una solicitud.")
        return redirect("cliente_perfil")
    form = None
    if request.method == "POST":
        form = SolicitudForm(request.POST, fotos=request.FILES.getlist("fotos"))
        if form.is_valid():
            solicitud = form.save(request.user)
            messages.success(request, "Solicitud creada. Avisamos a los técnicos disponibles de la categoría.")
            return redirect(f"{reverse('tecnicos')}?solicitud={solicitud.pk}")
    valores = request.POST if form else {"direccion": request.user.direccion}
    errores = [e for lista in form.errors.values() for e in lista] if form else []
    return render(request, "cliente/solicitud_nueva.html", _ctx(
        "cliente", categorias=d.CATEGORIAS, errores=errores, valores=valores,
        preseleccion=valores.get("categoria") or request.GET.get("categoria", "")))


@requiere_rol(Usuario.Rol.CLIENTE)
def tecnicos(request):
    solicitud_id = request.GET.get("solicitud")
    solicitud = None
    categoria = None
    if solicitud_id:
        solicitud = get_object_or_404(Solicitud, pk=solicitud_id, cliente=request.user)
        categoria = solicitud.categoria
    elif request.GET.get("categoria") in Categoria.values:
        categoria = request.GET["categoria"]

    tiene_ubicacion = _coordenadas_validas(request.user.latitud, request.user.longitud)
    cliente = {
        "nombre": request.user.nombre_completo,
        "direccion": request.user.direccion,
        "lat": request.user.latitud if tiene_ubicacion else None,
        "lng": request.user.longitud if tiene_ubicacion else None,
        "ubicacion_disponible": tiene_ubicacion,
    }
    tecnicos_disponibles = []
    sin_ubicacion = 0
    perfiles = PerfilTecnico.objects.select_related("usuario").filter(
        usuario__rol=Usuario.Rol.TECNICO,
        usuario__estado=Usuario.Estado.ACTIVO,
        disponible=True,
    )
    if categoria:
        perfiles = perfiles.filter(especialidad=categoria)
    for perfil in perfiles:
        datos = _datos_tarjeta_tecnico(
            perfil, cliente["lat"] if tiene_ubicacion else None,
            cliente["lng"] if tiene_ubicacion else None)
        if datos is None:
            sin_ubicacion += 1
            continue
        tecnicos_disponibles.append(datos)
    return render(request, "cliente/tecnicos.html", _ctx(
        "cliente", tecnicos=tecnicos_disponibles, cliente=cliente, solicitud=solicitud,
        categoria_nombre=dict(Categoria.choices).get(categoria), tecnicos_sin_ubicacion=sin_ubicacion))


@require_POST
@login_required
def actualizar_ubicacion(request):
    if request.user.rol not in (Usuario.Rol.CLIENTE, Usuario.Rol.TECNICO):
        return JsonResponse({"error": "Este perfil no puede registrar una ubicación."}, status=403)
    if request.user.esta_suspendido:
        return JsonResponse({"error": "Una cuenta suspendida no puede actualizar su ubicación."}, status=403)
    try:
        latitud = float(request.POST.get("latitud", ""))
        longitud = float(request.POST.get("longitud", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Las coordenadas recibidas no son válidas."}, status=400)
    if (
        not math.isfinite(latitud) or not math.isfinite(longitud)
        or not -90 <= latitud <= 90 or not -180 <= longitud <= 180
    ):
        return JsonResponse({"error": "Las coordenadas recibidas están fuera de rango."}, status=400)
    request.user.latitud = latitud
    request.user.longitud = longitud
    request.user.save(update_fields=["latitud", "longitud"])
    return JsonResponse({"ok": True})


@requiere_rol(Usuario.Rol.CLIENTE)
def cliente_historial(request):
    return render(request, "cliente/historial.html", _ctx("cliente", solicitudes=d.HISTORIAL_CLIENTE))


@requiere_rol(Usuario.Rol.CLIENTE)
def cliente_perfil(request):
    """FN-2: el cliente edita sus datos; correo nuevo requiere verificación."""
    if request.method == "POST":
        form = PerfilClienteForm(request.POST, usuario=request.user)
        if form.is_valid():
            correo_nuevo = form.cleaned_data["correo"]
            cambio_correo = correo_nuevo.casefold() != request.user.correo.casefold()
            form.save()
            update_session_auth_hash(request, request.user)
            if cambio_correo:
                token = signing.dumps(
                    {"usuario": request.user.pk, "correo": correo_nuevo},
                    salt="fixnow-verificar-correo-cliente",
                )
                url = request.build_absolute_uri(reverse(
                    "confirmar_correo_cliente", kwargs={"token": token}))
                send_mail(
                    "Confirma tu nuevo correo de FixNow",
                    f"Abre este enlace dentro de las próximas 24 horas para confirmar el cambio: {url}",
                    settings.DEFAULT_FROM_EMAIL, [correo_nuevo], fail_silently=False,
                )
                messages.success(request, "Perfil actualizado. Confirma el enlace enviado al correo nuevo; mientras tanto sigue activo el actual.")
            else:
                messages.success(request, "Perfil actualizado.")
            return redirect("cliente_perfil")
    else:
        form = PerfilClienteForm(usuario=request.user)
    return render(request, "cliente/perfil.html", _ctx(
        "cliente", form=form, sin_direccion=not request.user.direccion))


@requiere_rol(Usuario.Rol.CLIENTE)
def confirmar_correo_cliente(request, token):
    try:
        datos = signing.loads(token, salt="fixnow-verificar-correo-cliente", max_age=86400)
    except signing.SignatureExpired:
        messages.error(request, "El enlace venció. Solicita nuevamente el cambio de correo.")
        return redirect("cliente_perfil")
    except signing.BadSignature:
        messages.error(request, "El enlace de verificación no es válido.")
        return redirect("cliente_perfil")
    if datos.get("usuario") != request.user.pk:
        messages.error(request, "Este enlace pertenece a otra cuenta.")
    elif Usuario.objects.filter(correo__iexact=datos["correo"]).exclude(pk=request.user.pk).exists():
        messages.error(request, "Ese correo ya está registrado por otra cuenta.")
    else:
        request.user.correo = datos["correo"]
        request.user.save(update_fields=["correo"])
        messages.success(request, "Correo actualizado y verificado.")
    return redirect("cliente_perfil")


# ---------- Técnico ----------
ICONOS_CATEGORIA = {c["id"]: c["icono"] for c in d.CATEGORIAS}


def _solicitudes_para(tecnico):
    """FN-11: pendientes de mi especialidad, solo con disponibilidad activa, sin las que rechacé."""
    perfil = tecnico.perfil_tecnico
    if not perfil.disponible_para_solicitudes:
        return Solicitud.objects.none()
    return (Solicitud.objects
            .filter(estado=Solicitud.Estado.PENDIENTE, categoria=perfil.especialidad)
            .exclude(rechazada_por=tecnico)
            .select_related("cliente").prefetch_related("fotos")
            .order_by("-fecha_creacion"))


@requiere_rol(Usuario.Rol.TECNICO)
def tecnico_solicitudes(request):
    solicitudes = list(_solicitudes_para(request.user))
    for s in solicitudes:
        s.icono = ICONOS_CATEGORIA.get(s.categoria, "bi-tools")
        s.fotos_evidencia = [f for f in s.fotos.all() if f.tipo == "evidencia"]
    return render(request, "tecnico/solicitudes.html", _ctx(
        "tecnico", solicitudes=solicitudes, perfil=request.user.perfil_tecnico))


@require_POST
@requiere_rol(Usuario.Rol.TECNICO)
def tecnico_solicitud_accion(request, solicitud_id):
    """FN-11: aceptar o rechazar una solicitud pendiente de mi bandeja."""
    accion = request.POST.get("accion")
    if accion not in {"aceptar", "rechazar"}:
        return HttpResponseNotAllowed(["POST"])
    # Solo puede actuar sobre solicitudes que de verdad están en su bandeja.
    solicitud = _solicitudes_para(request.user).filter(pk=solicitud_id).first()
    if solicitud is None:
        messages.error(request, "Esta solicitud ya no está disponible.")
        return redirect("tecnico_solicitudes")
    if accion == "rechazar":
        solicitud.rechazar(request.user)
        messages.success(request, "Solicitud rechazada. Sigue disponible para otros técnicos.")
        return redirect("tecnico_solicitudes")
    try:
        solicitud.aceptar(request.user)
    except ValueError:  # otro técnico la aceptó primero
        messages.error(request, "Otro técnico aceptó esta solicitud primero; ya no está disponible.")
        return redirect("tecnico_solicitudes")
    Notificacion.objects.create(
        usuario=solicitud.cliente, tipo=Notificacion.Tipo.SOLICITUD_ACEPTADA, solicitud=solicitud,
        mensaje=f"{request.user.nombre_completo} aceptó tu solicitud de {solicitud.get_categoria_display()}.")
    messages.success(request, "Solicitud aceptada. Quedó en curso.")
    return redirect("tecnico_solicitudes")


@requiere_rol(Usuario.Rol.TECNICO)
def tecnico_perfil(request):
    if request.method == "POST":
        form = PerfilTecnicoForm(request.POST, request.FILES, usuario=request.user)
        if form.is_valid():
            correo_nuevo = form.cleaned_data["correo"].strip()
            cambio_correo = correo_nuevo.casefold() != request.user.correo.casefold()
            form.save()
            update_session_auth_hash(request, request.user)
            if cambio_correo:
                token = signing.dumps(
                    {"usuario": request.user.pk, "correo": correo_nuevo},
                    salt="fixnow-verificar-correo-tecnico",
                )
                url = request.build_absolute_uri(reverse(
                    "confirmar_correo_tecnico", kwargs={"token": token}
                ))
                send_mail(
                    "Confirma tu nuevo correo de FixNow",
                    f"Abre este enlace dentro de las próximas 24 horas para confirmar el cambio: {url}",
                    settings.DEFAULT_FROM_EMAIL, [correo_nuevo], fail_silently=False,
                )
                messages.success(request, "Perfil actualizado. Revisa el correo nuevo para confirmar el cambio de dirección.")
            else:
                messages.success(request, "Perfil actualizado.")
            return redirect("tecnico_perfil")
    else:
        form = PerfilTecnicoForm(usuario=request.user)
    return render(request, "tecnico/perfil.html", _ctx("tecnico", form=form))


@requiere_rol(Usuario.Rol.TECNICO)
def confirmar_correo_tecnico(request, token):
    try:
        datos = signing.loads(token, salt="fixnow-verificar-correo-tecnico", max_age=86400)
    except signing.SignatureExpired:
        messages.error(request, "El enlace venció. Solicita nuevamente el cambio de correo.")
        return redirect("tecnico_perfil")
    except signing.BadSignature:
        messages.error(request, "El enlace de verificación no es válido.")
        return redirect("tecnico_perfil")
    if datos.get("usuario") != request.user.pk:
        messages.error(request, "Este enlace pertenece a otra cuenta.")
    elif Usuario.objects.filter(correo__iexact=datos["correo"]).exclude(pk=request.user.pk).exists():
        messages.error(request, "Ese correo ya está registrado por otra cuenta.")
    else:
        request.user.correo = datos["correo"]
        request.user.save(update_fields=["correo"])
        messages.success(request, "Correo actualizado y verificado.")
    return redirect("tecnico_perfil")


@require_POST
@requiere_rol(Usuario.Rol.TECNICO)
def cambiar_disponibilidad(request):
    perfil = request.user.perfil_tecnico
    activar = request.POST.get("disponible") == "on"
    if request.user.estado != Usuario.Estado.ACTIVO:
        perfil.disponible = False
        perfil.save(update_fields=["disponible"])
        messages.error(request, "Solo una cuenta aprobada puede cambiar su disponibilidad.")
    else:
        perfil.disponible = activar
        perfil.save(update_fields=["disponible"])
        messages.success(request, "Disponibilidad activada." if activar else "Disponibilidad pausada.")
    return redirect("tecnico_solicitudes")


# ---------- Administrador ----------
@requiere_rol(Usuario.Rol.ADMINISTRADOR)
def admin_tecnicos(request):
    pendientes = Usuario.objects.filter(
        rol=Usuario.Rol.TECNICO,
        estado=Usuario.Estado.PENDIENTE_APROBACION,
    ).select_related("perfil_tecnico").order_by("date_joined")
    return render(request, "admin_panel/tecnicos.html", _ctx("admin", pendientes=pendientes))


@require_POST
@requiere_rol(Usuario.Rol.ADMINISTRADOR)
def admin_accion_tecnico(request, usuario_id):
    tecnico = get_object_or_404(
        Usuario, pk=usuario_id, rol=Usuario.Rol.TECNICO,
        estado=Usuario.Estado.PENDIENTE_APROBACION,
    )
    accion = request.POST.get("accion")
    motivo = request.POST.get("motivo", "").strip()
    if accion not in {"aprobar", "rechazar", "informacion"}:
        return HttpResponseNotAllowed(["POST"])
    if accion in {"rechazar", "informacion"} and not motivo:
        messages.error(request, "Escribe el motivo o la información que debe completar el técnico.")
        return redirect("admin_tecnicos")
    if len(motivo) > 300:
        messages.error(request, "El texto no puede superar 300 caracteres.")
        return redirect("admin_tecnicos")

    if accion == "aprobar":
        tecnico.estado = Usuario.Estado.ACTIVO
        tecnico.save(update_fields=["estado"])
        tipo = Notificacion.Tipo.TECNICO_APROBADO
        mensaje = "Tu cuenta fue aprobada. Ya puedes activar tu disponibilidad en FixNow."
    elif accion == "rechazar":
        tecnico.estado = Usuario.Estado.RECHAZADO
        tecnico.motivo_rechazo = motivo
        tecnico.save(update_fields=["estado", "motivo_rechazo"])
        tecnico.perfil_tecnico.disponible = False
        tecnico.perfil_tecnico.save(update_fields=["disponible"])
        tipo = Notificacion.Tipo.TECNICO_RECHAZADO
        mensaje = f"Tu registro fue rechazado: {motivo}"
    else:
        tipo = Notificacion.Tipo.INFO_SOLICITADA
        mensaje = f"Debes completar esta información: {motivo}"
    Notificacion.objects.create(usuario=tecnico, tipo=tipo, mensaje=mensaje)
    asuntos = {
        "aprobar": "Tu cuenta de técnico fue aprobada",
        "rechazar": "Actualización sobre tu registro en FixNow",
        "informacion": "Se requiere información para revisar tu registro",
    }
    send_mail(
        asuntos[accion], mensaje, settings.DEFAULT_FROM_EMAIL, [tecnico.correo],
        fail_silently=True,
    )
    messages.success(request, "Acción registrada y notificada al técnico.")
    return redirect("admin_tecnicos")


@requiere_rol(Usuario.Rol.ADMINISTRADOR)
def admin_certificacion(request, usuario_id):
    tecnico = get_object_or_404(
        Usuario.objects.select_related("perfil_tecnico"),
        pk=usuario_id, rol=Usuario.Rol.TECNICO,
    )
    archivo = tecnico.perfil_tecnico.documento_certificacion
    tipo = guess_type(archivo.name)[0] or "application/octet-stream"
    return FileResponse(archivo.open("rb"), content_type=tipo)
