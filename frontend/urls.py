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
    path("ubicacion/actualizar/", views.actualizar_ubicacion, name="actualizar_ubicacion"),
    path("cliente/historial/", views.cliente_historial, name="cliente_historial"),
    path("cliente/solicitudes/<int:solicitud_id>/calificar/", views.calificar_solicitud,
         name="calificar_solicitud"),
    path("cliente/solicitudes/<int:solicitud_id>/pagar/", views.pagar_solicitud,
         name="pagar_solicitud"),
    path("cliente/solicitudes/<int:solicitud_id>/comprobante/", views.comprobante_pago,
         name="comprobante_pago"),
    path("cliente/perfil/", views.cliente_perfil, name="cliente_perfil"),
    path("cliente/perfil/correo/<str:token>/", views.confirmar_correo_cliente,
         name="confirmar_correo_cliente"),
    # Técnico
    path("tecnico/solicitudes/", views.tecnico_solicitudes, name="tecnico_solicitudes"),
    path("tecnico/solicitudes/<int:solicitud_id>/accion/", views.tecnico_solicitud_accion,
         name="tecnico_solicitud_accion"),
    path("tecnico/solicitudes/<int:solicitud_id>/finalizar/", views.tecnico_finalizar,
         name="tecnico_finalizar"),
    path("tecnico/historial/", views.tecnico_historial, name="tecnico_historial"),
        path("tecnico/perfil/", views.tecnico_perfil, name="tecnico_perfil"),
        path("tecnico/perfil/correo/<str:token>/", views.confirmar_correo_tecnico,
            name="confirmar_correo_tecnico"),
        path("tecnico/disponibilidad/", views.cambiar_disponibilidad, name="cambiar_disponibilidad"),
    # Notificaciones (FN-19) y detalle de solicitud, para cualquier rol con sesión
    path("notificaciones/", views.notificaciones, name="notificaciones"),
    path("notificaciones/leer-todas/", views.notificaciones_leer_todas,
         name="notificaciones_leer_todas"),
    path("notificaciones/<int:notificacion_id>/leer/", views.notificacion_leer,
         name="notificacion_leer"),
    path("solicitudes/<int:solicitud_id>/", views.solicitud_detalle, name="solicitud_detalle"),
    # Administrador
    path("panel/tecnicos/", views.admin_tecnicos, name="admin_tecnicos"),
        path("panel/tecnicos/<int:usuario_id>/accion/", views.admin_accion_tecnico,
            name="admin_accion_tecnico"),
    path("panel/usuarios/", views.admin_usuarios, name="admin_usuarios"),
    path("panel/usuarios/<int:usuario_id>/accion/", views.admin_usuario_accion,
         name="admin_usuario_accion"),
    path("panel/reportes/", views.admin_reportes, name="admin_reportes"),
    path("panel/comision/", views.admin_comision, name="admin_comision"),
        path("panel/tecnicos/<int:usuario_id>/certificacion/", views.admin_certificacion,
            name="admin_certificacion"),
]
