document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-guardar-ubicacion]");
  if (!button) return;

  const message = button.parentElement.querySelector("[data-ubicacion-mensaje]");
  const showError = (text) => {
    message.textContent = text;
    message.hidden = false;
    message.classList.add("text-danger");
  };
  if (!navigator.geolocation) {
    showError("Este navegador no permite obtener la ubicación GPS.");
    return;
  }

  button.disabled = true;
  try {
    navigator.geolocation.getCurrentPosition(async ({ coords }) => {
      try {
        const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
        if (!csrf) throw new Error("No se pudo validar la solicitud. Recarga la página e inténtalo de nuevo.");
        const response = await fetch(button.dataset.url, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf },
          body: new URLSearchParams({ latitud: coords.latitude, longitud: coords.longitude }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "No se pudo guardar la ubicación.");
        window.location.reload();
      } catch (error) {
        showError(error.message || "No se pudo guardar la ubicación.");
        button.disabled = false;
      }
    }, (error) => {
      const messages = {
        1: "No autorizaste el GPS. Si ya guardaste una ubicación en tu perfil, esa ubicación seguirá usándose.",
        2: "No fue posible determinar tu ubicación. Inténtalo de nuevo o usa la ubicación guardada en tu perfil.",
        3: "La consulta de ubicación tardó demasiado. Inténtalo de nuevo.",
      };
      showError(messages[error.code] || "No se pudo obtener la ubicación GPS.");
      button.disabled = false;
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  } catch (error) {
    showError(error.message || "No se pudo obtener la ubicación GPS.");
    button.disabled = false;
  }
});
