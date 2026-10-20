import re

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Categoria, FotoSolicitud, Notificacion, PerfilTecnico, Solicitud, Usuario
from .validators import validar_certificacion, validar_foto

ATRS_TEXTO = "form-control"
ATRS_CHECK = "form-check-input"


def _campo_password(id_campo):
    """Comparte el widget entre FN-1 y FN-8 sin repetir el bloque completo."""
    return forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            "class": ATRS_TEXTO, "id": id_campo, "autocomplete": "new-password",
        }),
    )


def _campo_password2(id_campo):
    return forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={
            "class": ATRS_TEXTO, "id": id_campo, "autocomplete": "new-password",
        }),
    )


def _campo_terminos(id_campo):
    return forms.BooleanField(
        label="Acepto los términos y condiciones",
        error_messages={"required": "Debes aceptar los términos para continuar."},
        widget=forms.CheckboxInput(attrs={"class": ATRS_CHECK, "id": id_campo}),
    )


def _validar_politica_password(password):
    """FN-1/FN-8: mínimo 8 caracteres, una mayúscula, un número y un símbolo."""
    errores = []
    if len(password) < 8:
        errores.append("Debe tener al menos 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        errores.append("Debe incluir al menos una mayúscula.")
    if not re.search(r"\d", password):
        errores.append("Debe incluir al menos un número.")
    if not re.search(r"[^A-Za-z0-9]", password):
        errores.append("Debe incluir al menos un símbolo (por ejemplo ! # $ %).")
    if errores:
        raise ValidationError(errores)


class RegistroClienteForm(forms.ModelForm):
    """
    FN-1: registro de cliente. Los campos de Meta.fields ya traen su
    validación desde el modelo (cedula con regex de 6-10 dígitos, correo
    único, etc.) porque ModelForm llama a full_clean() del modelo solo.
    Contraseña y términos no son campos del modelo, así que se agregan
    aparte y se validan aquí.
    """

    password = _campo_password("password")
    password2 = _campo_password2("password2")
    terminos = _campo_terminos("terminos")

    class Meta:
        model = Usuario
        fields = ["cedula", "nombre_completo", "correo", "telefono"]
        widgets = {
            "cedula": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "cedula", "inputmode": "numeric",
                "maxlength": "10", "autocomplete": "off",
            }),
            "nombre_completo": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "nombre_completo", "autocomplete": "name",
            }),
            "correo": forms.EmailInput(attrs={
                "class": ATRS_TEXTO, "id": "correo", "autocomplete": "email",
            }),
            "telefono": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "telefono", "autocomplete": "tel",
            }),
        }
        error_messages = {
            "cedula": {"unique": "Ya existe una cuenta registrada con esta cédula."},
            "correo": {"unique": "Ya existe una cuenta registrada con este correo."},
        }

    def clean_password(self):
        password = self.cleaned_data["password"]
        _validar_politica_password(password)
        return password

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip()
        if Usuario.objects.filter(correo__iexact=correo).exists():
            raise ValidationError("Ya existe una cuenta registrada con este correo.")
        return correo

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cleaned

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.rol = Usuario.Rol.CLIENTE
        usuario.estado = Usuario.Estado.ACTIVO
        usuario.set_password(self.cleaned_data["password"])
        if commit:
            usuario.save()
        return usuario


class PerfilTecnicoForm(forms.Form):
    nombre_completo = forms.CharField(max_length=150, label="Nombre completo")
    telefono = forms.CharField(max_length=20, label="Teléfono")
    correo = forms.EmailField(label="Correo electrónico")
    especialidad = forms.ChoiceField(
        label="Especialidad", choices=Categoria.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    ciudad = forms.CharField(max_length=100, label="Ciudad")
    precio_referencia = forms.DecimalField(
        label="Precio de referencia", required=False, min_value=0,
        widget=forms.NumberInput(attrs={"min": "0", "step": "1000"}),
    )
    zona_cobertura = forms.CharField(
        label="Zona de cobertura", required=False, max_length=255,
    )
    foto_perfil = forms.ImageField(
        label="Foto de perfil", required=False, validators=[validar_foto],
    )
    password_actual = forms.CharField(
        label="Contraseña actual", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    password_nueva = forms.CharField(
        label="Nueva contraseña", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirmacion = forms.CharField(
        label="Confirmar nueva contraseña", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        self.perfil = usuario.perfil_tecnico
        kwargs.setdefault("initial", {
            "nombre_completo": usuario.nombre_completo,
            "telefono": usuario.telefono,
            "correo": usuario.correo,
            "especialidad": self.perfil.especialidad,
            "ciudad": self.perfil.ciudad,
            "precio_referencia": self.perfil.precio_referencia,
            "zona_cobertura": self.perfil.zona_cobertura,
        })
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput, forms.PasswordInput)):
                field.widget.attrs.setdefault("class", "form-control")

    def clean_correo(self):
        correo = self.cleaned_data["correo"]
        if Usuario.objects.filter(correo__iexact=correo).exclude(pk=self.usuario.pk).exists():
            raise ValidationError("Ya existe una cuenta registrada con este correo.")
        return correo

    def clean(self):
        cleaned = super().clean()
        actual = cleaned.get("password_actual")
        nueva = cleaned.get("password_nueva")
        confirmacion = cleaned.get("password_confirmacion")
        if actual or nueva or confirmacion:
            if not actual or not self.usuario.check_password(actual):
                self.add_error("password_actual", "La contraseña actual no es correcta.")
            if nueva:
                try:
                    _validar_politica_password(nueva)
                except ValidationError as error:
                    self.add_error("password_nueva", error)
            if nueva and confirmacion and nueva != confirmacion:
                self.add_error("password_confirmacion", "Las contraseñas no coinciden.")
            if not nueva:
                self.add_error("password_nueva", "Escribe la nueva contraseña.")
            if nueva and not confirmacion:
                self.add_error("password_confirmacion", "Confirma la nueva contraseña.")
        return cleaned

    def save(self):
        self.usuario.nombre_completo = self.cleaned_data["nombre_completo"]
        self.usuario.telefono = self.cleaned_data["telefono"]
        self.usuario.save(update_fields=["nombre_completo", "telefono"])

        for campo in ("especialidad", "ciudad", "precio_referencia", "zona_cobertura"):
            setattr(self.perfil, campo, self.cleaned_data[campo])
        if self.cleaned_data.get("foto_perfil"):
            self.perfil.foto_perfil = self.cleaned_data["foto_perfil"]
        self.perfil.save()

        if self.cleaned_data.get("password_nueva"):
            self.usuario.set_password(self.cleaned_data["password_nueva"])
            self.usuario.save(update_fields=["password"])
        return self.usuario


class PerfilClienteForm(forms.Form):
    """
    FN-2: edición de perfil del cliente.
    - La cédula no se incluye (dato legal permanente).
    - El correo NO se cambia aquí: se envía un enlace de verificación al correo
      nuevo y el actual sigue activo hasta confirmarlo (ver vistas).
    - Cambiar contraseña exige la actual y la política de seguridad.
    """

    nombre_completo = forms.CharField(max_length=150, label="Nombre completo")
    telefono = forms.CharField(max_length=20, label="Teléfono")
    correo = forms.EmailField(label="Correo electrónico")
    direccion = forms.CharField(max_length=255, label="Dirección")
    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    password_actual = forms.CharField(
        label="Contraseña actual", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    password_nueva = forms.CharField(
        label="Nueva contraseña", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirmacion = forms.CharField(
        label="Confirmar nueva contraseña", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        kwargs.setdefault("initial", {
            "nombre_completo": usuario.nombre_completo,
            "telefono": usuario.telefono,
            "correo": usuario.correo,
            "direccion": usuario.direccion,
            "fecha_nacimiento": usuario.fecha_nacimiento,
        })
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip()
        if Usuario.objects.filter(correo__iexact=correo).exclude(pk=self.usuario.pk).exists():
            raise ValidationError("Ya existe una cuenta registrada con este correo.")
        return correo

    def clean_direccion(self):
        direccion = self.cleaned_data["direccion"].strip()
        if not direccion:
            raise ValidationError("La dirección es obligatoria para poder crear solicitudes.")
        return direccion

    def clean(self):
        cleaned = super().clean()
        actual = cleaned.get("password_actual")
        nueva = cleaned.get("password_nueva")
        confirmacion = cleaned.get("password_confirmacion")
        if actual or nueva or confirmacion:
            if not actual or not self.usuario.check_password(actual):
                self.add_error("password_actual", "La contraseña actual no es correcta.")
            if not nueva:
                self.add_error("password_nueva", "Escribe la nueva contraseña.")
            else:
                try:
                    _validar_politica_password(nueva)
                except ValidationError as error:
                    self.add_error("password_nueva", error)
                if not confirmacion:
                    self.add_error("password_confirmacion", "Confirma la nueva contraseña.")
                elif nueva != confirmacion:
                    self.add_error("password_confirmacion", "Las contraseñas no coinciden.")
        return cleaned

    def save(self):
        u = self.usuario
        u.nombre_completo = self.cleaned_data["nombre_completo"]
        u.telefono = self.cleaned_data["telefono"]
        u.direccion = self.cleaned_data["direccion"]
        u.fecha_nacimiento = self.cleaned_data.get("fecha_nacimiento")
        campos = ["nombre_completo", "telefono", "direccion", "fecha_nacimiento"]
        if self.cleaned_data.get("password_nueva"):
            u.set_password(self.cleaned_data["password_nueva"])
            campos.append("password")
        u.save(update_fields=campos)
        return u


class SolicitudForm(forms.Form):
    """
    FN-3: crear solicitud de servicio. Las fotos llegan como varios archivos
    bajo el mismo nombre, por eso se validan aparte (ver `clean_fotos`).
    """

    MAX_FOTOS = 3

    categoria = forms.ChoiceField(
        choices=Categoria.choices,
        error_messages={"required": "Elige una categoría.", "invalid_choice": "Elige una categoría válida."},
    )
    descripcion = forms.CharField(
        min_length=10, max_length=300, strip=True,
        error_messages={"required": "Describe el problema.",
                        "min_length": "Describe el problema con al menos 10 caracteres.",
                        "max_length": "La descripción no puede superar 300 caracteres."},
    )
    direccion = forms.CharField(
        max_length=255, strip=True,
        error_messages={"required": "Escribe la dirección donde se hará el servicio."},
    )
    urgencia = forms.ChoiceField(
        choices=Solicitud.Urgencia.choices, required=False,
    )

    def __init__(self, *args, fotos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.archivos = [f for f in (fotos or []) if f.name]

    def clean_urgencia(self):
        return self.cleaned_data.get("urgencia") or Solicitud.Urgencia.NORMAL

    def clean(self):
        cleaned = super().clean()
        if len(self.archivos) > self.MAX_FOTOS:
            self.add_error(None, f"Puedes adjuntar máximo {self.MAX_FOTOS} fotos.")
        else:
            imagen = forms.ImageField(validators=[validar_foto])
            for archivo in self.archivos:
                try:
                    imagen.clean(archivo)
                except ValidationError as error:
                    self.add_error(None, f"{archivo.name}: {' '.join(error.messages)}")
        return cleaned

    def save(self, cliente):
        """Crea la solicitud 'pendiente' con sus fotos y la difunde a los técnicos."""
        with transaction.atomic():
            solicitud = Solicitud.objects.create(
                cliente=cliente,
                categoria=self.cleaned_data["categoria"],
                descripcion=self.cleaned_data["descripcion"],
                direccion=self.cleaned_data["direccion"],
                urgencia=self.cleaned_data["urgencia"],
            )  # estado=pendiente y fecha_creacion se asignan solos
            for archivo in self.archivos:
                FotoSolicitud.objects.create(
                    solicitud=solicitud, imagen=archivo, tipo=FotoSolicitud.Tipo.EVIDENCIA)
            # Difusión (modelo abierto, FN-11): a los técnicos aprobados, disponibles
            # y de la misma categoría; cada notificación va a un técnico concreto.
            tecnicos = Usuario.objects.filter(
                rol=Usuario.Rol.TECNICO, estado=Usuario.Estado.ACTIVO,
                perfil_tecnico__disponible=True,
                perfil_tecnico__especialidad=solicitud.categoria,
            )
            aviso = "Nueva solicitud urgente" if solicitud.urgencia == Solicitud.Urgencia.URGENTE else "Nueva solicitud"
            Notificacion.objects.bulk_create([
                Notificacion(
                    usuario=t, tipo=Notificacion.Tipo.SOLICITUD_CREADA, solicitud=solicitud,
                    mensaje=f"{aviso} de {solicitud.get_categoria_display()}.",
                ) for t in tecnicos
            ])
        return solicitud


class RegistroTecnicoForm(forms.ModelForm):
    """
    FN-8: a diferencia de FN-1, junta datos de dos modelos (Usuario y
    PerfilTecnico) en un solo formulario, y el usuario queda con estado
    'pendiente_aprobacion' en vez de quedar activo de una vez (ver FN-14).
    """

    especialidad = forms.ChoiceField(
        label="Especialidad",
        choices=[("", "Elige una")] + list(Categoria.choices),
        widget=forms.Select(attrs={"class": "form-select", "id": "especialidad"}),
    )
    ciudad = forms.CharField(
        label="Ciudad",
        widget=forms.TextInput(attrs={"class": ATRS_TEXTO, "id": "ciudad"}),
    )
    documento_certificacion = forms.FileField(
        label="Documento de certificación",
        validators=[validar_certificacion],
        error_messages={"required": "Adjunta tu certificación para poder registrarte."},
        widget=forms.ClearableFileInput(attrs={
            "class": ATRS_TEXTO, "id": "certificacion", "accept": "application/pdf,image/*",
        }),
    )
    password = _campo_password("password")
    password2 = _campo_password2("password2")
    terminos = _campo_terminos("terminos")

    class Meta:
        model = Usuario
        fields = ["cedula", "nombre_completo", "correo", "telefono"]
        widgets = {
            "cedula": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "cedula", "inputmode": "numeric",
                "maxlength": "10", "autocomplete": "off",
            }),
            "nombre_completo": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "nombre_completo", "autocomplete": "name",
            }),
            "correo": forms.EmailInput(attrs={
                "class": ATRS_TEXTO, "id": "correo", "autocomplete": "email",
            }),
            "telefono": forms.TextInput(attrs={
                "class": ATRS_TEXTO, "id": "telefono", "autocomplete": "tel",
            }),
        }
        error_messages = {
            "cedula": {"unique": "Ya existe una cuenta registrada con esta cédula."},
            "correo": {"unique": "Ya existe una cuenta registrada con este correo."},
        }

    def clean_password(self):
        password = self.cleaned_data["password"]
        _validar_politica_password(password)
        return password

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip()
        if Usuario.objects.filter(correo__iexact=correo).exists():
            raise ValidationError("Ya existe una cuenta registrada con este correo.")
        return correo

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cleaned

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.rol = Usuario.Rol.TECNICO
        usuario.estado = Usuario.Estado.PENDIENTE_APROBACION
        usuario.set_password(self.cleaned_data["password"])
        if commit:
            # Si falla la creación del perfil, no debe quedar un Usuario
            # huérfano sin PerfilTecnico asociado.
            with transaction.atomic():
                usuario.save()
                PerfilTecnico.objects.create(
                    usuario=usuario,
                    especialidad=self.cleaned_data["especialidad"],
                    ciudad=self.cleaned_data["ciudad"],
                    documento_certificacion=self.cleaned_data["documento_certificacion"],
                )
        return usuario
