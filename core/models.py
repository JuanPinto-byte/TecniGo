"""
Modelos de FixNow.

Un solo lugar para todo el esquema, pensado para que las 20 historias
(FN-1 a FN-20) no necesiten cambios de estructura más adelante.
Cada campo tiene un comentario con la historia que lo pide, para que
puedan revisar contra el documento de sprints.

Categorías, estados y roles están centralizados en clases *Choices*
para no repetir strings sueltos por el código (y para que coincidan
exactamente con los valores que ya usa el frontend en
frontend/datos_falsos.py).
"""
from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .validators import validar_cedula, validar_certificacion, validar_foto


# =====================================================================
# Catálogos compartidos
# =====================================================================

class Categoria(models.TextChoices):
    """Mismos ids que frontend/datos_falsos.py, para no duplicar el catálogo."""
    PLOMERIA = "plomeria", "Plomería"
    ELECTRICIDAD = "electricidad", "Electricidad"
    CERRAJERIA = "cerrajeria", "Cerrajería"
    ELECTRODOMESTICOS = "electrodomesticos", "Electrodomésticos"
    OTRO = "otro", "Otro"


# =====================================================================
# Usuario (FN-1, FN-8, FN-14, FN-15)
# =====================================================================

class UsuarioManager(BaseUserManager):
    """Manager mínimo para poder loguear por correo en vez de username."""

    def _crear(self, correo, password, **extra):
        if not correo:
            raise ValueError("El usuario debe tener correo.")
        correo = self.normalize_email(correo)
        usuario = self.model(correo=correo, **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo, password=None, **extra):
        extra.setdefault("rol", Usuario.Rol.CLIENTE)
        extra.setdefault("estado", Usuario.Estado.ACTIVO)
        return self._crear(correo, password, **extra)

    def create_superuser(self, correo, password=None, **extra):
        extra.setdefault("rol", Usuario.Rol.ADMINISTRADOR)
        extra.setdefault("estado", Usuario.Estado.ACTIVO)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._crear(correo, password, **extra)


class Usuario(AbstractUser):
    """
    Cliente, técnico y administrador son el mismo modelo con distinto `rol`,
    porque comparten casi todos los campos (FN-1 y FN-8 piden lo mismo salvo
    especialidad/documento, que por eso viven en PerfilTecnico, no aquí).

    Se usa `correo` en vez del `username` de Django para iniciar sesión.
    """

    class Rol(models.TextChoices):
        CLIENTE = "cliente", "Cliente"
        TECNICO = "tecnico", "Técnico"
        ADMINISTRADOR = "administrador", "Administrador"

    class Estado(models.TextChoices):
        ACTIVO = "activo", "Activo"
        # Solo técnicos pasan por aquí (FN-8); un cliente nace en ACTIVO (FN-1).
        PENDIENTE_APROBACION = "pendiente_aprobacion", "Pendiente de aprobación"
        RECHAZADO = "rechazado", "Rechazado"
        SUSPENDIDO = "suspendido", "Suspendido"

    username = None  # no se usa: se inicia sesión con correo
    email = None  # se reemplaza por 'correo' para mantener el resto del proyecto en español

    correo = models.EmailField("correo electrónico", unique=True)
    cedula = models.CharField(max_length=10, unique=True, validators=[validar_cedula])
    nombre_completo = models.CharField(max_length=150)
    telefono = models.CharField(max_length=20)
    rol = models.CharField(max_length=20, choices=Rol.choices)
    estado = models.CharField(max_length=25, choices=Estado.choices, default=Estado.ACTIVO)

    # FN-2: dirección y fecha de nacimiento (solo se piden/editan para clientes).
    direccion = models.CharField(max_length=255, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)

    # FN-4/FN-20: ubicación para calcular distancia y pintar el mapa.
    # Sirve tanto para el cliente (GPS o esta misma dirección) como para el
    # técnico (su punto de referencia dentro de su zona de cobertura).
    latitud = models.FloatField(null=True, blank=True)
    longitud = models.FloatField(null=True, blank=True)

    # FN-15: motivo y fecha de una suspensión (aplica a cliente o técnico).
    motivo_suspension = models.CharField(max_length=300, blank=True)
    fecha_suspension = models.DateTimeField(null=True, blank=True)

    # FN-14: motivo cuando un admin rechaza a un técnico.
    motivo_rechazo = models.CharField(max_length=300, blank=True)

    USERNAME_FIELD = "correo"
    REQUIRED_FIELDS = ["cedula", "nombre_completo", "telefono", "rol"]

    objects = UsuarioManager()

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.nombre_completo} ({self.get_rol_display()})"

    # ---- Reglas de negocio reutilizables (evitan repetir lógica en las vistas) ----

    @property
    def esta_suspendido(self):
        return self.estado == self.Estado.SUSPENDIDO

    @property
    def puede_iniciar_sesion(self):
        """FN-15: un usuario suspendido no puede iniciar sesión."""
        return not self.esta_suspendido

    def suspender(self, motivo):
        """FN-15: suspende y, si es técnico, fuerza su disponibilidad a inactivo."""
        self.estado = self.Estado.SUSPENDIDO
        self.motivo_suspension = motivo
        self.fecha_suspension = timezone.now()
        self.save(update_fields=["estado", "motivo_suspension", "fecha_suspension"])
        if self.rol == self.Rol.TECNICO and hasattr(self, "perfil_tecnico"):
            self.perfil_tecnico.disponible = False
            self.perfil_tecnico.save(update_fields=["disponible"])

    def reactivar(self):
        """FN-15: vuelve a 'activo'; el técnico no recupera disponibilidad solo."""
        self.estado = self.Estado.ACTIVO
        self.motivo_suspension = ""
        self.fecha_suspension = None
        self.save(update_fields=["estado", "motivo_suspension", "fecha_suspension"])


class PerfilTecnico(models.Model):
    """
    Datos exclusivos de un técnico (FN-8, FN-9, FN-10).
    Separado de Usuario porque un cliente nunca tiene estos campos.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_tecnico"
    )
    especialidad = models.CharField(max_length=30, choices=Categoria.choices)
    ciudad = models.CharField(max_length=100)

    # FN-8: obligatorio para completar el registro.
    documento_certificacion = models.FileField(
        upload_to="certificaciones/", validators=[validar_certificacion]
    )
    foto_perfil = models.ImageField(upload_to="fotos_perfil/", null=True, blank=True)

    # FN-9: se editan después del registro; por eso empiezan vacíos/"a convenir".
    precio_referencia = models.DecimalField(
        max_digits=10, decimal_places=0, null=True, blank=True
    )
    zona_cobertura = models.CharField(max_length=255, blank=True)

    # FN-10: solo se puede activar si el técnico ya está aprobado (ver clean()).
    disponible = models.BooleanField(default=False)

    # FN-4/FN-7: se recalculan cada vez que llega una calificación nueva
    # (Calificacion.save más abajo), para no tener que promediar en cada consulta.
    calificacion_promedio = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_calificaciones = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Perfil de técnico"
        verbose_name_plural = "Perfiles de técnico"

    def __str__(self):
        return f"Perfil técnico de {self.usuario.nombre_completo}"

    @property
    def precio_referencia_txt(self):
        """FN-5: 'a convenir' cuando no hay precio definido."""
        if self.precio_referencia is None:
            return "a convenir"
        return f"${self.precio_referencia:,.0f}".replace(",", ".")

    @property
    def disponible_para_solicitudes(self):
        """FN-4/FN-10: un técnico solo aparece si está aprobado, activo y disponible."""
        return (
            self.usuario.estado == Usuario.Estado.ACTIVO
            and self.disponible
        )


# =====================================================================
# Solicitud (FN-3, FN-11, FN-12) y sus fotos (FN-3, FN-12)
# =====================================================================

class Solicitud(models.Model):
    """
    FN-3: la crea el cliente. FN-11: un técnico la acepta (modelo abierto:
    se ofrece a todos los técnicos disponibles de la categoría, gana el
    primero que acepta). FN-12: el técnico asignado la finaliza.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_CURSO = "en_curso", "En curso"
        FINALIZADA = "finalizada", "Finalizada"
        CANCELADA = "cancelada", "Cancelada"

    class Urgencia(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENTE = "urgente", "Urgente"

    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes_creadas",
        limit_choices_to={"rol": Usuario.Rol.CLIENTE},
    )
    # Null mientras está "pendiente"; FN-11 lo llena al aceptar.
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes_asignadas",
        limit_choices_to={"rol": Usuario.Rol.TECNICO}, null=True, blank=True,
    )

    categoria = models.CharField(max_length=30, choices=Categoria.choices)
    descripcion = models.CharField(max_length=300, validators=[MinLengthValidator(10)])
    direccion = models.CharField(max_length=255)
    urgencia = models.CharField(max_length=10, choices=Urgencia.choices, default=Urgencia.NORMAL)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)

    # FN-11: técnicos que ya la rechazaron, para no volver a mostrársela
    # (el criterio no lo exige explícitamente, pero sin esto un técnico
    # que rechazó la seguiría viendo en su bandeja).
    rechazada_por = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="solicitudes_rechazadas", blank=True
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    fecha_finalizacion = models.DateTimeField(null=True, blank=True)

    # FN-12: notas opcionales al finalizar.
    notas_finales = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return f"Solicitud #{self.pk} — {self.get_categoria_display()} ({self.get_estado_display()})"

    # ---- Transiciones de estado, para que las vistas no dupliquen lógica ----

    def aceptar(self, tecnico):
        """
        FN-11: solo si sigue pendiente. El UPDATE condicional es atómico en la
        base de datos: si dos técnicos aceptan a la vez, solo uno modifica la fila.
        """
        ahora = timezone.now()
        filas = Solicitud.objects.filter(pk=self.pk, estado=self.Estado.PENDIENTE).update(
            tecnico=tecnico, estado=self.Estado.EN_CURSO, fecha_asignacion=ahora)
        if filas == 0:
            raise ValueError("La solicitud ya no está disponible.")
        self.tecnico = tecnico
        self.estado = self.Estado.EN_CURSO
        self.fecha_asignacion = ahora

    def rechazar(self, tecnico):
        """FN-11: sigue pendiente y disponible para los demás técnicos."""
        self.rechazada_por.add(tecnico)

    def finalizar(self, notas=""):
        """FN-12: solo el técnico asignado y solo si está en curso (validar en la vista)."""
        if self.estado != self.Estado.EN_CURSO:
            raise ValueError("Solo se puede finalizar una solicitud en curso.")
        self.estado = self.Estado.FINALIZADA
        self.fecha_finalizacion = timezone.now()
        self.notas_finales = notas
        self.save(update_fields=["estado", "fecha_finalizacion", "notas_finales"])

    @property
    def puede_calificarse(self):
        """FN-7."""
        return self.estado == self.Estado.FINALIZADA and not hasattr(self, "calificacion")

    @property
    def puede_pagarse(self):
        """FN-17."""
        return self.estado == self.Estado.FINALIZADA and not (
            hasattr(self, "pago") and self.pago.estado == Pago.Estado.EXITOSO
        )


class FotoSolicitud(models.Model):
    """FN-3: hasta 3 fotos de evidencia al crear. FN-12: foto opcional al finalizar."""

    class Tipo(models.TextChoices):
        EVIDENCIA = "evidencia", "Evidencia del daño"
        FINALIZACION = "finalizacion", "Evidencia de finalización"

    solicitud = models.ForeignKey(Solicitud, on_delete=models.CASCADE, related_name="fotos")
    imagen = models.ImageField(upload_to="solicitudes/", validators=[validar_foto])
    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.EVIDENCIA)

    def __str__(self):
        return f"Foto {self.get_tipo_display()} de la solicitud #{self.solicitud_id}"


# =====================================================================
# Calificación (FN-7, FN-13)
# =====================================================================

class Calificacion(models.Model):
    """FN-7: una por solicitud finalizada, no editable después de enviada."""

    solicitud = models.OneToOneField(Solicitud, on_delete=models.CASCADE, related_name="calificacion")
    estrellas = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.CharField(max_length=300, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.estrellas}★ a {self.solicitud.tecnico} (solicitud #{self.solicitud_id})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._recalcular_promedio_tecnico()

    def _recalcular_promedio_tecnico(self):
        """FN-7: cada calificación nueva recalcula el promedio usado en FN-4."""
        perfil = self.solicitud.tecnico.perfil_tecnico
        calificaciones = Calificacion.objects.filter(solicitud__tecnico=self.solicitud.tecnico)
        total = calificaciones.count()
        promedio = calificaciones.aggregate(models.Avg("estrellas"))["estrellas__avg"] or 0
        perfil.total_calificaciones = total
        perfil.calificacion_promedio = round(promedio, 2)
        perfil.save(update_fields=["total_calificaciones", "calificacion_promedio"])


# =====================================================================
# Notificaciones (FN-19)
# =====================================================================

class Notificacion(models.Model):
    """FN-19: una notificación in-app dirigida a un solo usuario."""

    class Tipo(models.TextChoices):
        SOLICITUD_CREADA = "solicitud_creada", "Solicitud creada"
        SOLICITUD_ACEPTADA = "solicitud_aceptada", "Solicitud aceptada"
        SOLICITUD_FINALIZADA = "solicitud_finalizada", "Solicitud finalizada"
        TECNICO_APROBADO = "tecnico_aprobado", "Técnico aprobado"
        TECNICO_RECHAZADO = "tecnico_rechazado", "Técnico rechazado"
        INFO_SOLICITADA = "info_solicitada", "Información solicitada"
        USUARIO_SUSPENDIDO = "usuario_suspendido", "Usuario suspendido"
        PAGO_EXITOSO = "pago_exitoso", "Pago exitoso"
        PAGO_FALLIDO = "pago_fallido", "Pago fallido"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificaciones"
    )
    tipo = models.CharField(max_length=25, choices=Tipo.choices)
    mensaje = models.CharField(max_length=255)
    # FN-19: si viene de una solicitud, tocarla navega a su detalle.
    solicitud = models.ForeignKey(
        Solicitud, on_delete=models.CASCADE, related_name="notificaciones", null=True, blank=True
    )
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return f"[{'leída' if self.leida else 'nueva'}] {self.mensaje}"


# =====================================================================
# Pagos y comisión (FN-17, FN-18)
# =====================================================================

class ConfiguracionComision(models.Model):
    """
    FN-18: porcentaje configurable, no fijo en el código.
    Se maneja como fila única (singleton simple, sin librerías extra).
    """

    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de comisión"
        verbose_name_plural = "Configuración de comisión"

    def __str__(self):
        return f"Comisión actual: {self.porcentaje}%"

    @classmethod
    def actual(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class Pago(models.Model):
    """FN-17: pago en modo sandbox de la pasarela, ver nota en el documento de sprints."""

    class Medio(models.TextChoices):
        TARJETA = "tarjeta", "Tarjeta"
        PSE = "pse", "PSE"
        BILLETERA = "billetera", "Billetera digital"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EXITOSO = "exitoso", "Exitoso"
        FALLIDO = "fallido", "Fallido"

    solicitud = models.OneToOneField(Solicitud, on_delete=models.PROTECT, related_name="pago")
    medio_pago = models.CharField(max_length=15, choices=Medio.choices)
    monto = models.DecimalField(max_digits=10, decimal_places=0)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)
    # Id que devuelve la pasarela en sandbox (Wompi/ePayco/Mercado Pago); nunca
    # se guardan datos sensibles como número de tarjeta o CVV (regla de FN-17).
    referencia_pasarela = models.CharField(max_length=100, blank=True)
    motivo_fallo = models.CharField(max_length=255, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pago {self.get_estado_display()} — solicitud #{self.solicitud_id}"

    def marcar_exitoso(self, referencia_pasarela):
        """FN-17 + FN-18: al quedar exitoso, dispara el cálculo de comisión."""
        self.estado = self.Estado.EXITOSO
        self.referencia_pasarela = referencia_pasarela
        self.save(update_fields=["estado", "referencia_pasarela"])
        Comision.calcular_para(self)

    def marcar_fallido(self, motivo):
        self.estado = self.Estado.FALLIDO
        self.motivo_fallo = motivo
        self.save(update_fields=["estado", "motivo_fallo"])


class Comision(models.Model):
    """FN-18: se calcula automáticamente cuando un Pago pasa a exitoso."""

    pago = models.OneToOneField(Pago, on_delete=models.CASCADE, related_name="comision")
    porcentaje_aplicado = models.DecimalField(max_digits=5, decimal_places=2)
    monto_comision = models.DecimalField(max_digits=10, decimal_places=0)
    monto_neto_tecnico = models.DecimalField(max_digits=10, decimal_places=0)
    fecha_calculo = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comisión de ${self.monto_comision:,.0f} (pago #{self.pago_id})".replace(",", ".")

    @classmethod
    def calcular_para(cls, pago):
        """
        FN-18: monto de comisión = monto × porcentaje; neto = monto − comisión.
        Guarda el porcentaje aplicado (no solo el actual) para que un cambio
        futuro de configuración no altere comisiones ya calculadas.
        """
        porcentaje = ConfiguracionComision.actual().porcentaje
        monto_comision = round(pago.monto * porcentaje / 100)
        return cls.objects.create(
            pago=pago,
            porcentaje_aplicado=porcentaje,
            monto_comision=monto_comision,
            monto_neto_tecnico=pago.monto - monto_comision,
        )
