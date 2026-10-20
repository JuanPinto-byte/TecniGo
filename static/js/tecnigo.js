/* TecniGo - comportamientos comunes del frontend */

// ---- Toast ----
function fxToast(mensaje) {
  const el = document.getElementById("fx-toast");
  if (!el) return;
  el.querySelector(".toast-body").textContent = mensaje;
  bootstrap.Toast.getOrCreateInstance(el, { delay: 2600 }).show();
}

document.addEventListener("DOMContentLoaded", () => {
  // Enlaces a pantallas que todavía no existen
  document.querySelectorAll("[data-pronto]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      fxToast("Esta pantalla aún no está construida");
    });
  });

  // ---- Contraseña: política + confirmación (FN-1, FN-8) ----
  document.querySelectorAll("form[data-pass-form]").forEach((form) => {
    const p1 = form.querySelector("#password");
    const p2 = form.querySelector("#password2");
    const reglas = form.querySelectorAll("[data-regla]");
    const tests = {
      largo: (v) => v.length >= 8,
      mayus: (v) => /[A-Z]/.test(v),
      numero: (v) => /\d/.test(v),
      simbolo: (v) => /[^A-Za-z0-9]/.test(v),
    };
    const validar = () => {
      let todas = true;
      reglas.forEach((li) => {
        const ok = tests[li.dataset.regla](p1.value);
        li.classList.toggle("ok", ok);
        todas = todas && ok;
      });
      p1.setCustomValidity(todas ? "" : "La contraseña no cumple los requisitos");
      p2.setCustomValidity(p1.value === p2.value ? "" : "Las contraseñas no coinciden");
    };
    p1.addEventListener("input", validar);
    p2.addEventListener("input", validar);
    validar();
  });

  // ---- Validación Bootstrap al enviar ----
  document.querySelectorAll("form.needs-validation").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!form.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
        const primero = form.querySelector(":invalid");
        if (primero) primero.focus();
      }
      form.classList.add("was-validated");
    });
  });

  // ---- Contador de caracteres ----
  document.querySelectorAll("[data-counter]").forEach((area) => {
    const salida = document.querySelector(area.dataset.counter);
    const min = parseInt(area.getAttribute("minlength") || "0", 10);
    const max = parseInt(area.getAttribute("maxlength") || "0", 10);
    const pintar = () => {
      const n = area.value.length;
      salida.textContent = max ? `${n}/${max}` : `${n}`;
      salida.classList.toggle("text-danger", n > 0 && n < min);
    };
    area.addEventListener("input", pintar);
    pintar();
  });

  // ---- Límite de archivos: tamaño y cantidad ----
  document.querySelectorAll("input[type=file][data-max-mb]").forEach((input) => {
    input.addEventListener("change", () => {
      const maxMb = parseFloat(input.dataset.maxMb);
      const maxFiles = parseInt(input.dataset.maxFiles || "1", 10);
      const archivos = [...input.files];
      let error = "";
      if (archivos.length > maxFiles) error = `Máximo ${maxFiles} archivo(s)`;
      else if (archivos.some((f) => f.size > maxMb * 1024 * 1024)) error = `Cada archivo debe pesar máximo ${maxMb} MB`;
      input.setCustomValidity(error);
      if (error) {
        fxToast(error);
        input.value = "";
        input.setCustomValidity("");
      }
    });
  });
});
