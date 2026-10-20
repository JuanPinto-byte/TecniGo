from django.urls import path

from . import views

urlpatterns = [
    # Público
    path("", views.landing, name="landing"),
    path("ingresar/", views.login_view, name="login"),
    path("salir/", views.cerrar_sesion, name="logout"),
    path("registro/", views.registro_cliente, name="registro_cliente"),
    path("registro/tecnico/", views.registro_tecnico, name="registro_tecnico"),
    # Cliente
    path("cliente/", views.cliente_inicio, name="cliente_inicio"),
    path("cliente/solicitud/nueva/", views.solicitud_nueva, name="solicitud_nueva"),
    path("cliente/tecnicos/", views.tecnicos, name="tecnicos"),
    path("cliente/historial/", views.cliente_historial, name="cliente_historial"),
    path("cliente/perfil/", views.cliente_perfil, name="cliente_perfil"),
    path("cliente/perfil/correo/<str:token>/", views.confirmar_correo_cliente,
         name="confirmar_correo_cliente"),
    # Técnico
    path("tecnico/solicitudes/", views.tecnico_solicitudes, name="tecnico_solicitudes"),
    path("tecnico/solicitudes/<int:solicitud_id>/accion/", views.tecnico_solicitud_accion,
         name="tecnico_solicitud_accion"),
        path("tecnico/perfil/", views.tecnico_perfil, name="tecnico_perfil"),
        path("tecnico/perfil/correo/<str:token>/", views.confirmar_correo_tecnico,
            name="confirmar_correo_tecnico"),
        path("tecnico/disponibilidad/", views.cambiar_disponibilidad, name="cambiar_disponibilidad"),
    # Administrador
    path("panel/tecnicos/", views.admin_tecnicos, name="admin_tecnicos"),
        path("panel/tecnicos/<int:usuario_id>/accion/", views.admin_accion_tecnico,
            name="admin_accion_tecnico"),
        path("panel/tecnicos/<int:usuario_id>/certificacion/", views.admin_certificacion,
            name="admin_certificacion"),
]
