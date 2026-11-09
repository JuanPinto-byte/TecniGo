from django.test import TestCase
from django.urls import reverse

from core.forms import PerfilClienteForm
from core.models import Categoria, PerfilTecnico, Solicitud, Usuario
from frontend.datos_falsos import haversine_km


class TecnicosDisponiblesTests(TestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user(
            correo="cliente@example.com",
            password="ClaveSegura123!",
            cedula="123456",
            nombre_completo="Cliente de Prueba",
            telefono="3001234567",
            rol=Usuario.Rol.CLIENTE,
            direccion="Calle 10",
            latitud=4.65,
            longitud=-74.06,
        )
        self.solicitud = Solicitud.objects.create(
            cliente=self.cliente,
            categoria=Categoria.PLOMERIA,
            descripcion="Fuga de agua en la cocina",
            direccion="Calle 10",
        )
        self.plomero = self.crear_tecnico(
            "plomero@example.com", "654321", Categoria.PLOMERIA, 4.656, -74.059
        )
        self.crear_tecnico(
            "electricista@example.com", "789012", Categoria.ELECTRICIDAD, 4.651, -74.061
        )
        self.crear_tecnico(
            "inactivo@example.com", "345678", Categoria.PLOMERIA, 4.652, -74.062,
            disponible=False,
        )
        self.client.force_login(self.cliente)

    def crear_tecnico(
        self, correo, cedula, especialidad, latitud, longitud, disponible=True
    ):
        tecnico = Usuario.objects.create_user(
            correo=correo,
            password="ClaveSegura123!",
            cedula=cedula,
            nombre_completo=f"Técnico {cedula}",
            telefono="3001234567",
            rol=Usuario.Rol.TECNICO,
            estado=Usuario.Estado.ACTIVO,
            latitud=latitud,
            longitud=longitud,
        )
        PerfilTecnico.objects.create(
            usuario=tecnico,
            especialidad=especialidad,
            ciudad="Bogotá",
            documento_certificacion="certificaciones/prueba.pdf",
            disponible=disponible,
        )
        return tecnico

    def test_listing_is_scoped_to_owned_request_category_and_does_not_assign(self):
        response = self.client.get(
            reverse("tecnicos"), {"solicitud": self.solicitud.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.context["tecnicos"]], [self.plomero.pk])
        self.assertAlmostEqual(
            response.context["tecnicos"][0]["km"],
            haversine_km(4.65, -74.06, 4.656, -74.059),
        )
        self.assertNotContains(response, "Enviar solicitud")
        self.solicitud.refresh_from_db()
        self.assertIsNone(self.solicitud.tecnico)

    def test_request_from_another_customer_is_not_visible(self):
        otro_cliente = Usuario.objects.create_user(
            correo="otro@example.com",
            password="ClaveSegura123!",
            cedula="222222",
            nombre_completo="Otro Cliente",
            telefono="3001234567",
            rol=Usuario.Rol.CLIENTE,
        )
        otra_solicitud = Solicitud.objects.create(
            cliente=otro_cliente,
            categoria=Categoria.PLOMERIA,
            descripcion="Fuga en el baño",
            direccion="Calle 20",
        )

        response = self.client.get(
            reverse("tecnicos"), {"solicitud": otra_solicitud.pk}
        )

        self.assertEqual(response.status_code, 404)

    def test_home_uses_real_available_technicians(self):
        response = self.client.get(reverse("cliente_inicio"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plomero.nombre_completo)
        self.assertContains(response, "Sin calificaciones")
        self.assertNotIn(
            "Camilo Restrepo",
            [tecnico["nombre"] for tecnico in response.context["tecnicos"]],
        )

    def test_location_endpoint_saves_only_valid_coordinates(self):
        response = self.client.post(
            reverse("actualizar_ubicacion"),
            {"latitud": "4.7", "longitud": "-74.1"},
        )

        self.assertEqual(response.status_code, 200)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.latitud, 4.7)
        self.assertEqual(self.cliente.longitud, -74.1)

        response = self.client.post(
            reverse("actualizar_ubicacion"),
            {"latitud": "91", "longitud": "-74.1"},
        )

        self.assertEqual(response.status_code, 400)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.latitud, 4.7)

    def test_changing_profile_address_clears_old_location(self):

        form = PerfilClienteForm(
            {
                "nombre_completo": self.cliente.nombre_completo,
                "telefono": self.cliente.telefono,
                "correo": self.cliente.correo,
                "direccion": "Calle 11",
                "fecha_nacimiento": "",
                "password_actual": "",
                "password_nueva": "",
                "password_confirmacion": "",
            },
            usuario=self.cliente,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.cliente.refresh_from_db()
        self.assertIsNone(self.cliente.latitud)
        self.assertIsNone(self.cliente.longitud)
