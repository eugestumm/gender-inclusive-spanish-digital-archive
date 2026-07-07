---
title: Uso de Neomorfemas a lo Largo del Tiempo
layout: default
---

<div class="responsive-network-iframe">
  <iframe
    id="gsi-viz-frame"
    src="{{ site.baseurl }}/data-visualization/visualization-neomorphemes-over-time-es.html"
    loading="lazy"
    allowfullscreen
  ></iframe>
</div>

<style>
.responsive-network-iframe {
  width: 100%;
  height: 1400px; /* fallback: guaranteed visible even if JS resize never fires */
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  margin: 20px 0;
}
.responsive-network-iframe iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}
@media (max-width: 768px) {
  .responsive-network-iframe {
    height: 2200px; /* your content stacks taller on narrow screens (chart + long table) */
    margin: 10px -15px;
    border-radius: 0;
  }
}
</style>

<script>
  window.addEventListener("message", function (e) {
    if (e.data && e.data.type === "gsi-viz-height") {
      var frame = document.getElementById("gsi-viz-frame");
      frame.style.height = e.data.height + "px";
      frame.parentElement.style.height = e.data.height + "px";
    }
  });
</script>
