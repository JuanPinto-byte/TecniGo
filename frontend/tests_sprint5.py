"""
Sprint 5 (TDD): FN-12 finalizar, FN-6 historial del cliente, FN-13 historial del
técnico, FN-7 calificar y FN-19 notificaciones.

Estas pruebas se escribieron ANTES que el código (fase roja) y luego se
implementó lo mínimo para ponerlas en verde.
"""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import (
    Calificacion, Categoria, FotoSolicitud, Notificacion, PerfilTecnico, Solicitud, Usuario,
)

CLAVE = "ClaveSegura123!"
_contador = iter(range(100000, 999999))


def png(nombre="evidencia.png"):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, "PNG")
    return SimpleUploadedFile(nombre, buf.getvalue(), content_type="image/png")


class Base(TestCase):
    def crear_cliente(self, nombre="Cliente Uno"):
        n = next(_contador)
        return Usuario.objects.create_user(
            correo=f"c{n}@example.com", password=CLAVE, cedula=str(n), nombre_completo=nombre,
            telefono="3001234567", rol=Usuario.Rol.CLIENTE, direccion="Calle 10 # 5-5")

    def crear_tecnico(self, nombre="Técnico Uno", especialidad=Categoria.PLOMERIA, disponible=True):
        n = next(_contador)
        u = Usuario.objects.create_user(
            correo=f"t{n}@example.com", password=CLAVE, cedula=str(n), nombre_completo=nombre,
            telefono="3001234567", rol=Usuario.Rol.TECNICO, estado=Usuario.Estado.ACTIVO)
        PerfilTecnico.objects.create(
            usuario=u, especialidad=especialidad, ciudad="Bogotá",
            documento_certificacion="certificaciones/x.pdf", disponible=disponible)
        return u

    def crear_admin(self):
        n = next(_contador)
        return Usuario.objects.create_user(
            correo=f"a{n}@example.com", password=CLAVE, cedula=str(n), nombre_completo="Admin",
            telefono="3001234567", rol=Usuario.Rol.ADMINISTRADOR)

    def crear_solicitud(self, cliente, estado=Solicitud.Estado.PENDIENTE, tecnico=None,
                        categoria=Categoria.PLOMERIA, descripcion="Fuga de agua en la cocina"):
        s = Solicitud.objects.create(
            cliente=cliente, tecnico=tecnico, categoria=categoria, estado=estado,
            descripcion=descripcion, direccion="Calle 10 # 5-5")
        return s

    def en_curso(self, cliente, tecnico, **kw):
        return self.crear_solicitud(cliente, Solicitud.Estado.EN_CURSO, tecnico, **kw)

    def finalizada(self, cliente, tecnico, **kw):
        return self.crear_solicitud(cliente, Solicitud.Estado.FINALIZADA, tecnico, **kw)


# =====================================================================
# FN-12 — Finalizar solicitud
# =====================================================================
class FinalizarSolicitudTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.solicitud = self.en_curso(self.cliente, self.tecnico)
        self.url = reverse("tecnico_finalizar", args=[self.solicitud.pk])
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_el_tecnico_asignado_finaliza_y_se_registra_fecha(self):
        self.client.force_login(self.tecnico)
        r = self.client.post(self.url, {"notas": "Cambié el sifón"})
        self.assertEqual(r.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.FINALIZADA)
        self.assertIsNotNone(self.solicitud.fecha_finalizacion)
        self.assertEqual(self.solicitud.notas_finales, "Cambié el sifón")

    def test_notas_son_opcionales(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.FINALIZADA)

    def test_notas_limite_300_si_301_no(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {"notas": "x" * 301})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_CURSO)
        self.client.post(self.url, {"notas": "x" * 300})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.FINALIZADA)

    def test_finalizar_no_cambia_la_disponibilidad(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {})
        self.assertTrue(self.tecnico.perfil_tecnico.__class__.objects.get(
            usuario=self.tecnico).disponible)
        perfil = self.tecnico.perfil_tecnico
        perfil.disponible = False
        perfil.save()
        otra = self.en_curso(self.cliente, self.tecnico)
        self.client.post(reverse("tecnico_finalizar", args=[otra.pk]), {})
        perfil.refresh_from_db()
        self.assertFalse(perfil.disponible)

    def test_otro_tecnico_no_puede_finalizar(self):
        intruso = self.crear_tecnico("Intruso")
        self.client.force_login(intruso)
        r = self.client.post(self.url, {})
        self.assertEqual(r.status_code, 404)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_CURSO)

    def test_no_se_finaliza_una_pendiente(self):
        pendiente = self.crear_solicitud(self.cliente)
        self.client.force_login(self.tecnico)
        r = self.client.post(reverse("tecnico_finalizar", args=[pendiente.pk]), {})
        self.assertEqual(r.status_code, 404)
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Solicitud.Estado.PENDIENTE)

    def test_finalizar_dos_veces_no_duplica_notificacion(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {})
        self.client.post(self.url, {})
        self.assertEqual(Notificacion.objects.filter(
            usuario=self.cliente, tipo=Notificacion.Tipo.SOLICITUD_FINALIZADA).count(), 1)

    def test_modelo_finalizar_con_instancia_vieja_falla(self):
        a = Solicitud.objects.get(pk=self.solicitud.pk)
        b = Solicitud.objects.get(pk=self.solicitud.pk)
        a.finalizar("primera")
        with self.assertRaises(ValueError):
            b.finalizar("segunda")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.notas_finales, "primera")

    def test_notifica_al_cliente_con_enlace_a_la_solicitud(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {})
        n = Notificacion.objects.get(usuario=self.cliente, tipo=Notificacion.Tipo.SOLICITUD_FINALIZADA)
        self.assertEqual(n.solicitud, self.solicitud)
        self.assertFalse(n.leida)

    def test_cliente_no_puede_finalizar(self):
        self.client.force_login(self.cliente)
        r = self.client.post(self.url, {})
        self.assertEqual(r.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_CURSO)

    def test_get_no_permitido(self):
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_sin_sesion_redirige(self):
        r = self.client.post(self.url, {})
        self.assertEqual(r.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_CURSO)

    def test_foto_opcional_de_finalizacion(self):
        with override_settings(MEDIA_ROOT=self.tmp):
            self.client.force_login(self.tecnico)
            self.client.post(self.url, {"foto": png()})
        foto = FotoSolicitud.objects.get(solicitud=self.solicitud)
        self.assertEqual(foto.tipo, FotoSolicitud.Tipo.FINALIZACION)

    def test_foto_con_formato_invalido_se_rechaza(self):
        malo = SimpleUploadedFile("virus.exe", b"MZ....", content_type="application/octet-stream")
        with override_settings(MEDIA_ROOT=self.tmp):
            self.client.force_login(self.tecnico)
            self.client.post(self.url, {"foto": malo})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_CURSO)
        self.assertFalse(FotoSolicitud.objects.exists())


# =====================================================================
# FN-6 — Historial del cliente
# =====================================================================
class HistorialClienteTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico("Camilo Técnico")
        self.pend = self.crear_solicitud(self.cliente, descripcion="Pendiente de plomería")
        self.curso = self.en_curso(self.cliente, self.tecnico, descripcion="En curso de plomería")
        self.fin = self.finalizada(self.cliente, self.tecnico, descripcion="Finalizada de plomería")
        self.canc = self.crear_solicitud(self.cliente, Solicitud.Estado.CANCELADA,
                                         descripcion="Cancelada de plomería")
        self.url = reverse("cliente_historial")
        self.client.force_login(self.cliente)

    def ids(self, r):
        return [s["id"] for s in r.context["solicitudes"]]

    def test_muestra_todos_los_estados_mas_reciente_primero(self):
        r = self.client.get(self.url)
        self.assertEqual(self.ids(r), [self.canc.pk, self.fin.pk, self.curso.pk, self.pend.pk])

    def test_orden_antigua_primero(self):
        r = self.client.get(self.url, {"orden": "antigua"})
        self.assertEqual(self.ids(r), [self.pend.pk, self.curso.pk, self.fin.pk, self.canc.pk])

    def test_orden_invalido_usa_el_defecto(self):
        r = self.client.get(self.url, {"orden": "'; DROP TABLE"})
        self.assertEqual(self.ids(r)[0], self.canc.pk)

    def test_filtra_por_cada_estado(self):
        esperado = {"pendiente": self.pend, "en_curso": self.curso,
                    "finalizada": self.fin, "cancelada": self.canc}
        for estado, solicitud in esperado.items():
            r = self.client.get(self.url, {"estado": estado})
            self.assertEqual(self.ids(r), [solicitud.pk], estado)

    def test_estado_invalido_equivale_a_todas(self):
        r = self.client.get(self.url, {"estado": "inventado"})
        self.assertEqual(len(self.ids(r)), 4)

    def test_nunca_ve_solicitudes_de_otro_cliente(self):
        otro = self.crear_cliente("Otro Cliente")
        ajena = self.crear_solicitud(otro, descripcion="Ajena secreta")
        r = self.client.get(self.url)
        self.assertNotIn(ajena.pk, self.ids(r))
        self.assertNotContains(r, "Ajena secreta")

    def test_tecnico_asignado_o_sin_asignar(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Camilo Técnico")
        self.assertContains(r, "Sin asignar")

    def test_atajo_para_calificar_solo_si_finalizada_y_sin_calificar(self):
        r = self.client.get(self.url)
        self.assertContains(r, reverse("calificar_solicitud", args=[self.fin.pk]))
        self.assertNotContains(r, reverse("calificar_solicitud", args=[self.curso.pk]))
        Calificacion.objects.create(solicitud=self.fin, estrellas=4)
        r = self.client.get(self.url)
        self.assertNotContains(r, reverse("calificar_solicitud", args=[self.fin.pk]))

    def test_estado_vacio_con_acceso_a_crear_solicitud(self):
        nuevo = self.crear_cliente("Sin solicitudes")
        self.client.force_login(nuevo)
        r = self.client.get(self.url)
        self.assertEqual(self.ids(r), [])
        self.assertContains(r, reverse("solicitud_nueva"))

    def test_filtro_sin_resultados_informa(self):
        Solicitud.objects.filter(cliente=self.cliente, estado="cancelada").delete()
        r = self.client.get(self.url, {"estado": "cancelada"})
        self.assertEqual(self.ids(r), [])
        self.assertContains(r, "No tienes solicitudes en este estado")

    def test_un_tecnico_no_entra(self):
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_sin_sesion_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_ya_no_usa_datos_falsos(self):
        r = self.client.get(self.url)
        self.assertNotContains(r, "Laura Gómez")


# =====================================================================
# FN-13 — Historial del técnico
# =====================================================================
class HistorialTecnicoTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente("Cliente Historial")
        self.tecnico = self.crear_tecnico()
        self.curso = self.en_curso(self.cliente, self.tecnico, descripcion="Trabajo en curso")
        self.fin = self.finalizada(self.cliente, self.tecnico, descripcion="Trabajo terminado")
        self.pend = self.crear_solicitud(self.cliente, descripcion="Aún pendiente")
        otro = self.crear_tecnico("Otro Técnico")
        self.ajena = self.en_curso(self.cliente, otro, descripcion="De otro técnico")
        self.url = reverse("tecnico_historial")
        self.client.force_login(self.tecnico)

    def ids(self, r):
        return [s["id"] for s in r.context["servicios"]]

    def test_solo_propias_en_curso_y_finalizadas(self):
        r = self.client.get(self.url)
        self.assertEqual(self.ids(r), [self.fin.pk, self.curso.pk])
        self.assertNotContains(r, "De otro técnico")
        self.assertNotContains(r, "Aún pendiente")

    def test_orden_antiguo_primero(self):
        r = self.client.get(self.url, {"orden": "antigua"})
        self.assertEqual(self.ids(r), [self.curso.pk, self.fin.pk])

    def test_filtros_por_estado(self):
        self.assertEqual(self.ids(self.client.get(self.url, {"estado": "en_curso"})), [self.curso.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {"estado": "finalizada"})), [self.fin.pk])
        self.assertEqual(len(self.ids(self.client.get(self.url, {"estado": "pendiente"}))), 2)
        self.assertEqual(len(self.ids(self.client.get(self.url, {"estado": "zzz"}))), 2)

    def test_muestra_cliente_y_calificacion(self):
        Calificacion.objects.create(solicitud=self.fin, estrellas=4, comentario="Muy amable")
        r = self.client.get(self.url)
        self.assertContains(r, "Cliente Historial")
        self.assertContains(r, "Muy amable")
        self.assertContains(r, "Sin calificar")  # la de en curso

    def test_en_curso_tiene_acceso_para_finalizar_y_finalizada_no(self):
        r = self.client.get(self.url)
        self.assertContains(r, reverse("tecnico_finalizar", args=[self.curso.pk]))
        self.assertNotContains(r, reverse("tecnico_finalizar", args=[self.fin.pk]))

    def test_calificacion_solo_lectura(self):
        Calificacion.objects.create(solicitud=self.fin, estrellas=5, comentario="Excelente")
        r = self.client.post(self.url, {"estrellas": 1})
        self.assertEqual(r.status_code, 405)
        self.assertEqual(Calificacion.objects.get(solicitud=self.fin).estrellas, 5)

    def test_historial_vacio(self):
        nuevo = self.crear_tecnico("Recién llegado")
        self.client.force_login(nuevo)
        r = self.client.get(self.url)
        self.assertEqual(self.ids(r), [])

    def test_cliente_no_entra(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_tecnico_suspendido_no_entra(self):
        self.tecnico.suspender("incumplimiento")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)


# =====================================================================
# FN-7 — Calificar el servicio
# =====================================================================
class CalificarTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.solicitud = self.finalizada(self.cliente, self.tecnico)
        self.url = reverse("calificar_solicitud", args=[self.solicitud.pk])
        self.client.force_login(self.cliente)

    def total(self):
        return Calificacion.objects.count()

    def test_califica_con_estrellas_y_comentario(self):
        r = self.client.post(self.url, {"estrellas": "5", "comentario": "Todo perfecto"})
        self.assertEqual(r.status_code, 302)
        c = Calificacion.objects.get(solicitud=self.solicitud)
        self.assertEqual((c.estrellas, c.comentario), (5, "Todo perfecto"))

    def test_limites_de_estrellas_validos_1_y_5(self):
        for n in (1, 5):
            s = self.finalizada(self.cliente, self.tecnico)
            self.client.post(reverse("calificar_solicitud", args=[s.pk]), {"estrellas": str(n)})
            self.assertEqual(Calificacion.objects.get(solicitud=s).estrellas, n)

    def test_estrellas_invalidas_se_rechazan(self):
        for valor in ("0", "6", "-1", "abc", "", "5.5", " ", "99999999999"):
            self.client.post(self.url, {"estrellas": valor})
            self.assertEqual(self.total(), 0, repr(valor))

    def test_sin_estrellas_se_rechaza(self):
        self.client.post(self.url, {"comentario": "solo texto"})
        self.assertEqual(self.total(), 0)

    def test_comentario_limite_300_si_301_no(self):
        self.client.post(self.url, {"estrellas": "3", "comentario": "x" * 301})
        self.assertEqual(self.total(), 0)
        self.client.post(self.url, {"estrellas": "3", "comentario": "x" * 300})
        self.assertEqual(self.total(), 1)

    def test_comentario_es_opcional(self):
        self.client.post(self.url, {"estrellas": "4"})
        self.assertEqual(Calificacion.objects.get().comentario, "")

    def test_solo_se_califica_una_vez_y_no_se_edita(self):
        self.client.post(self.url, {"estrellas": "5", "comentario": "Primera"})
        self.client.post(self.url, {"estrellas": "1", "comentario": "Segunda"})
        self.assertEqual(self.total(), 1)
        c = Calificacion.objects.get()
        self.assertEqual((c.estrellas, c.comentario), (5, "Primera"))
        perfil = self.tecnico.perfil_tecnico
        perfil.refresh_from_db()
        self.assertEqual(perfil.total_calificaciones, 1)

    def test_recalcula_el_promedio_del_tecnico(self):
        segunda = self.finalizada(self.cliente, self.tecnico)
        self.client.post(self.url, {"estrellas": "5"})
        self.client.post(reverse("calificar_solicitud", args=[segunda.pk]), {"estrellas": "2"})
        perfil = self.tecnico.perfil_tecnico
        perfil.refresh_from_db()
        self.assertEqual(perfil.total_calificaciones, 2)
        self.assertEqual(float(perfil.calificacion_promedio), 3.5)

    def test_solo_si_esta_finalizada(self):
        for estado in (Solicitud.Estado.EN_CURSO, Solicitud.Estado.PENDIENTE, Solicitud.Estado.CANCELADA):
            s = self.crear_solicitud(self.cliente, estado, self.tecnico if estado == "en_curso" else None)
            self.client.post(reverse("calificar_solicitud", args=[s.pk]), {"estrellas": "5"})
        self.assertEqual(self.total(), 0)

    def test_no_se_califica_una_solicitud_ajena(self):
        otro = self.crear_cliente("Otro")
        self.client.force_login(otro)
        r = self.client.post(self.url, {"estrellas": "5"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.total(), 0)

    def test_el_tecnico_no_puede_calificar(self):
        self.client.force_login(self.tecnico)
        self.client.post(self.url, {"estrellas": "5"})
        self.assertEqual(self.total(), 0)

    def test_get_no_permitido(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_sin_sesion_redirige(self):
        self.client.logout()
        self.client.post(self.url, {"estrellas": "5"})
        self.assertEqual(self.total(), 0)

    def test_comentario_con_html_se_escapa_en_el_historial_del_tecnico(self):
        self.client.post(self.url, {"estrellas": "5", "comentario": "<script>alert(1)</script>"})
        self.client.force_login(self.tecnico)
        r = self.client.get(reverse("tecnico_historial"))
        self.assertNotContains(r, "<script>alert(1)</script>")


# =====================================================================
# FN-19 — Notificaciones in-app
# =====================================================================
class NotificacionesTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.solicitud = self.en_curso(self.cliente, self.tecnico)

    def notif(self, usuario, mensaje="Hola", leida=False, solicitud=None):
        return Notificacion.objects.create(
            usuario=usuario, tipo=Notificacion.Tipo.SOLICITUD_ACEPTADA, mensaje=mensaje,
            leida=leida, solicitud=solicitud)

    def test_la_campana_cuenta_solo_mis_no_leidas(self):
        self.notif(self.cliente)
        self.notif(self.cliente)
        self.notif(self.cliente, leida=True)
        self.notif(self.tecnico)
        self.client.force_login(self.cliente)
        r = self.client.get(reverse("cliente_historial"))
        self.assertEqual(r.context["n_notif"], 2)

    def test_sin_notificaciones_la_campana_es_cero(self):
        self.client.force_login(self.cliente)
        r = self.client.get(reverse("cliente_historial"))
        self.assertEqual(r.context["n_notif"], 0)

    def test_el_encabezado_usa_los_datos_reales_del_cliente(self):
        self.client.force_login(self.cliente)
        r = self.client.get(reverse("cliente_historial"))
        self.assertContains(r, "Calle 10 # 5-5")

    def test_listado_muestra_solo_las_propias_en_cada_rol(self):
        admin = self.crear_admin()
        for usuario in (self.cliente, self.tecnico, admin):
            self.notif(usuario, f"Mensaje de {usuario.pk}")
        for usuario in (self.cliente, self.tecnico, admin):
            self.client.force_login(usuario)
            r = self.client.get(reverse("notificaciones"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, f"Mensaje de {usuario.pk}")
            for otro in (self.cliente, self.tecnico, admin):
                if otro != usuario:
                    self.assertNotContains(r, f"Mensaje de {otro.pk}")

    def test_listado_vacio(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("notificaciones")).status_code, 200)

    def test_sin_sesion_redirige(self):
        self.assertEqual(self.client.get(reverse("notificaciones")).status_code, 302)

    def test_marcar_una_como_leida(self):
        n = self.notif(self.cliente)
        otra = self.notif(self.cliente)
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("notificacion_leer", args=[n.pk]))
        self.assertEqual(r.status_code, 302)
        n.refresh_from_db(); otra.refresh_from_db()
        self.assertTrue(n.leida)
        self.assertFalse(otra.leida)

    def test_no_se_puede_marcar_la_de_otro_usuario(self):
        ajena = self.notif(self.tecnico)
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("notificacion_leer", args=[ajena.pk]))
        self.assertEqual(r.status_code, 404)
        ajena.refresh_from_db()
        self.assertFalse(ajena.leida)

    def test_marcar_una_inexistente_da_404(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.post(reverse("notificacion_leer", args=[99999])).status_code, 404)

    def test_marcar_todas_solo_afecta_las_mias(self):
        a = self.notif(self.cliente); b = self.notif(self.cliente)
        ajena = self.notif(self.tecnico)
        self.client.force_login(self.cliente)
        self.client.post(reverse("notificaciones_leer_todas"))
        for n in (a, b, ajena):
            n.refresh_from_db()
        self.assertTrue(a.leida and b.leida)
        self.assertFalse(ajena.leida)

    def test_marcar_todas_sin_pendientes_no_falla(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.post(reverse("notificaciones_leer_todas")).status_code, 302)

    def test_get_no_cambia_nada(self):
        n = self.notif(self.cliente)
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("notificacion_leer", args=[n.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("notificaciones_leer_todas")).status_code, 405)
        n.refresh_from_db()
        self.assertFalse(n.leida)

    def test_tocar_una_con_solicitud_navega_al_detalle(self):
        n = self.notif(self.cliente, solicitud=self.solicitud)
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("notificacion_leer", args=[n.pk]))
        self.assertRedirects(r, reverse("solicitud_detalle", args=[self.solicitud.pk]),
                             fetch_redirect_response=False)

    def test_tocar_una_sin_solicitud_vuelve_al_listado(self):
        n = self.notif(self.cliente)
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("notificacion_leer", args=[n.pk]))
        self.assertRedirects(r, reverse("notificaciones"), fetch_redirect_response=False)

    def test_detalle_visible_para_el_cliente_dueno_y_el_tecnico_asignado(self):
        url = reverse("solicitud_detalle", args=[self.solicitud.pk])
        for usuario in (self.cliente, self.tecnico):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_detalle_oculto_para_terceros(self):
        url = reverse("solicitud_detalle", args=[self.solicitud.pk])
        for intruso in (self.crear_cliente("Intruso"), self.crear_tecnico("Intruso T")):
            self.client.force_login(intruso)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_detalle_de_pendiente_visible_para_tecnico_elegible(self):
        pend = self.crear_solicitud(self.cliente)
        elegible = self.crear_tecnico("Elegible")
        no_elegible = self.crear_tecnico("Electricista", Categoria.ELECTRICIDAD)
        url = reverse("solicitud_detalle", args=[pend.pk])
        self.client.force_login(elegible)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(no_elegible)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_aceptar_notifica_solo_al_cliente_de_esa_solicitud(self):
        pend = self.crear_solicitud(self.cliente)
        otro = self.crear_cliente("Otro")
        self.client.force_login(self.tecnico)
        self.client.post(reverse("tecnico_solicitud_accion", args=[pend.pk]), {"accion": "aceptar"})
        self.assertEqual(Notificacion.objects.filter(
            usuario=self.cliente, tipo=Notificacion.Tipo.SOLICITUD_ACEPTADA, solicitud=pend).count(), 1)
        self.assertEqual(Notificacion.objects.filter(usuario=otro).count(), 0)
