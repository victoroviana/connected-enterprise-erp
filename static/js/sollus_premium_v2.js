/* ==============================================================================
   SOLLUS CONNECTED - PREMIUM INTERACTIVE HELPER V2
   Auto CountUp, Smooth Tooltips & Status Pulse Enhancements
   ============================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  // 1. CountUp animation for numeric stats
  function animateValue(obj, start, end, duration) {
    let startTimestamp = null;
    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      const current = Math.floor(progress * (end - start) + start);
      obj.innerHTML = current.toLocaleString("pt-BR");
      if (progress < 1) {
        window.requestAnimationFrame(step);
      }
    };
    window.requestAnimationFrame(step);
  }

  // Target numeric stat values
  const statElements = document.querySelectorAll(".stat-card h3, .metric-card h3, .hero-stat .value, [data-countup='true']");
  statElements.forEach((el) => {
    const text = el.innerText.trim().replace(/\D/g, "");
    if (text && !isNaN(text) && text.length < 7 && text.length > 0) {
      const targetVal = parseInt(text, 10);
      if (targetVal > 0) {
        animateValue(el, 0, targetVal, 800);
      }
    }
  });

  // 2. Auto-fade alerts after 5 seconds
  const autoAlerts = document.querySelectorAll(".alert-dismissible");
  autoAlerts.forEach((alert) => {
    setTimeout(() => {
      if (alert && alert.classList.contains("show")) {
        alert.style.transition = "opacity 0.4s ease, transform 0.4s ease";
        alert.style.opacity = "0";
        alert.style.transform = "translateY(-10px)";
        setTimeout(() => alert.remove(), 400);
      }
    }, 5500);
  });
});
