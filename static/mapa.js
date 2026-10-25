/* Mapas de Mi Trabajo. Una sola capa fina sobre Leaflet, compartida por las
   cuatro pantallas que muestran un mapa (alta de seccional, ficha, "Mi
   seccional" del afiliado y el mapa del Panel Sindical).

   Existe para que la URL de las teselas, la atribución de OpenStreetMap, la
   ruta de los íconos del globo y el armado de los enlaces "cómo llegar"
   estén en UN lugar. Cuatro copias de esto es lo que hace que un día tres
   mapas tengan la atribución y el cuarto no.

   Leaflet va VENDOREADO en /static/vendor/leaflet/ (nunca CDN, mismo
   criterio que Chart.js). Las TESELAS sí salen a openstreetmap.org en cada
   uso: no se pueden cachear ni copiar, es su política. Sin conexión, el
   mapa no dibuja y la pantalla muestra la dirección en texto. */
(function (global) {
  "use strict";

  // Los PNG del globo por default de Leaflet se resuelven relativos al CSS;
  // como el CSS está en /static/vendor/leaflet/, hay que decírselo
  // explícito o el globo sale roto y sin ícono.
  if (global.L && L.Icon && L.Icon.Default) {
    L.Icon.Default.imagePath = "/static/vendor/leaflet/images/";
  }

  var TESELAS = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  // Obligatoria por la licencia de OSM. No se saca ni se achica.
  var ATRIBUCION = '&copy; colaboradores de <a href="https://www.openstreetmap.org/copyright" ' +
                   'target="_blank" rel="noopener">OpenStreetMap</a>';

  // Centro del país, para abrir un mapa que todavía no tiene nada que mostrar.
  var CENTRO_AR = [-38.5, -63.6];

  function capaBase(mapa) {
    L.tileLayer(TESELAS, { maxZoom: 19, attribution: ATRIBUCION }).addTo(mapa);
  }

  /* Crea un mapa. `alMover` se llama con (lat, lon) cada vez que el usuario
     suelta el globo: es lo que convierte una ubicación en `manual`.

     `alTocar` (opcional) hace lo mismo al TOCAR el mapa, poniendo el globo
     ahí si todavía no hay ninguno. Existe para el único caso en que no hay
     nada que arrastrar: la dirección no se encontró (o los servicios de
     geocodificación no respondieron) y la persona tiene que marcar el punto
     desde cero. Sin esto, ese caso obligaría a arrastrar un globo puesto en
     el medio del país. */
  function crear(elemento, opciones) {
    opciones = opciones || {};
    var el = typeof elemento === "string" ? document.getElementById(elemento) : elemento;
    if (!el || !global.L) return null;

    var tiene = typeof opciones.lat === "number" && typeof opciones.lon === "number";
    var mapa = L.map(el, { scrollWheelZoom: opciones.rueda !== false })
                .setView(tiene ? [opciones.lat, opciones.lon] : CENTRO_AR,
                         tiene ? (opciones.zoom || 16) : 4);
    capaBase(mapa);

    var globo = null;
    if (tiene) {
      globo = L.marker([opciones.lat, opciones.lon],
                       { draggable: !!opciones.arrastrable }).addTo(mapa);
      if (opciones.arrastrable && opciones.alMover) {
        globo.on("dragend", function () {
          var p = globo.getLatLng();
          opciones.alMover(p.lat, p.lng);
        });
      }
      if (opciones.popup) globo.bindPopup(opciones.popup);
    }

    if (opciones.alTocar) {
      mapa.on("click", function (ev) {
        opciones.alTocar(ev.latlng.lat, ev.latlng.lng);
      });
    }

    return {
      mapa: mapa,
      globo: globo,
      /* Mueve (o crea) el globo y centra. Se usa al elegir un candidato de
         la lista sin tener que destruir y rehacer el mapa. */
      ir: function (lat, lon, zoom) {
        if (!globo) {
          globo = L.marker([lat, lon], { draggable: !!opciones.arrastrable }).addTo(mapa);
          if (opciones.arrastrable && opciones.alMover) {
            globo.on("dragend", function () {
              var p = globo.getLatLng();
              opciones.alMover(p.lat, p.lng);
            });
          }
        } else {
          globo.setLatLng([lat, lon]);
        }
        mapa.setView([lat, lon], zoom || opciones.zoom || 16);
      },
      /* Redibuja. Leaflet mide el contenedor al crearse: si el mapa nace
         dentro de algo oculto (un modal, un paso del asistente) queda con
         tamaño 0 y se ve gris. Hay que llamar a esto al mostrarlo. */
      refrescar: function () { setTimeout(function () { mapa.invalidateSize(); }, 60); },
      encuadrar: function (puntos) {
        if (!puntos || !puntos.length) return;
        mapa.fitBounds(L.latLngBounds(puntos), { padding: [30, 30], maxZoom: 15 });
      }
    };
  }

  /* ---------- Burbujas de seccional ----------

     Las usan los DOS mapas de la app (el del Panel Sindical y el del
     dashboard de una encuesta) y viven acá por lo mismo que la atribución de
     OSM: dos copias es lo que hace que un día un mapa se vea distinto del
     otro y nadie sepa cuál es el bueno.

     Una burbuja dice tres cosas a la vez:
       - su TAMAÑO, una cantidad (afiliados, participantes);
       - su BORDE, dónde cae en una escala (el % de participación, la métrica
         elegida);
       - su RELLENO, si está seleccionada o no.
     Y adentro lleva el logo del sindicato en marca de agua, que es lo que
     hace que el mapa se lea como parte de la app del gremio y no como un
     mapa cualquiera con puntos. */

  // Escala FIJA de la app, no la marca del sindicato: es cuantitativa, y con
  // el acento de cada gremio la misma intensidad significaría otra cosa en
  // cada tenant. De poco (claro) a mucho (oscuro).
  var ESCALA = ["#dbe4f0", "#a9c1de", "#6f97c6", "#3f6fa8", "#1e4877"];
  var SIN_DATO = "#cfd6e0";

  function colorEscala(valor, maximo) {
    if (valor === null || valor === undefined) return SIN_DATO;
    if (!maximo) return ESCALA[0];
    var i = Math.min(ESCALA.length - 1, Math.floor(valor / maximo * ESCALA.length));
    return ESCALA[i];
  }

  /* El diámetro va por RAÍZ CUADRADA y no lineal: lo que el ojo compara es
     el área del círculo, así que con tamaño lineal una seccional del doble de
     gente se ve cuatro veces más grande. Va de 18 a 46 px: más chico no se
     puede tocar con el dedo, más grande tapa a las vecinas en el conurbano. */
  function diametroBurbuja(valor, maximo) {
    return 2 * (9 + Math.sqrt(Math.max(0, valor || 0) / (maximo || 1)) * 14);
  }

  /* Un marcador con forma de burbuja. Es un `divIcon` y no un
     `L.circleMarker` porque un círculo de SVG no puede llevar una imagen
     adentro sin armar un `<pattern>` por marcador; con HTML el logo es un
     background y el CSS vive en marca.css, donde se lo puede leer. */
  function burbuja(lat, lon, o) {
    o = o || {};
    var d = Math.max(14, Math.round(o.diametro || 26));
    var borde = o.seleccionada ? 3.5 : 2.5;
    var estilo = "border-width:" + borde + "px;border-color:" + (o.borde || "#ffffff") +
                 ";background-color:" + (o.relleno || "#ffffff") + ";";
    // El logo se pasa como URL de la propia app; se le sacan las comillas por
    // si algún día la arma otro y mete algo raro en el `url(...)`.
    var logo = o.logo ? '<i style="background-image:url(' +
               String(o.logo).replace(/["'\\()\s]/g, "") + ')"></i>' : "";
    var marca = L.marker([lat, lon], {
      icon: L.divIcon({
        className: "mt-burbuja-wrap",
        html: '<span class="mt-burbuja' + (o.seleccionada ? " sel" : "") +
              '" style="' + estilo + '">' + logo + "</span>",
        iconSize: [d, d], iconAnchor: [d / 2, d / 2]
      }),
      keyboard: false,
      // Mantiene a las chicas por encima de las grandes: si no, una burbuja
      // de 46 px tapa a la de 18 y no hay forma de tocarla.
      zIndexOffset: Math.round(1000 - d)
    });
    // Dónde está de verdad y cuánto mide: lo que necesita `separarBurbujas`
    // para correrla sin perder su lugar real.
    marca._lugar = L.latLng(lat, lon);
    marca._diametro = d;
    return marca;
  }

  /* ---------- Encuadre de los mapas de tablero ----------

     Una sola regla para los DOS mapas de burbujas (Panel Sindical y
     Resultados de encuesta), así encuadran igual: todas las burbujas adentro,
     con 56 px de aire (el radio de la más grande más un margen: con 30 la de
     Córdoba quedaba cortada contra el borde) y nunca más cerca que zoom 7
     (con dos seccionales en la misma ciudad, el mapa se iba a nivel de
     barrio y se perdía dónde quedan).

     El zoom va en pasos de un cuarto solo en estos mapas: con pasos enteros
     el que cabía en el alto saltaba un nivel entero hacia afuera y entraban
     Chile y el sur de Brasil con las burbujas chiquitas en el medio. Se mide
     el contenedor ANTES de encuadrar: si Leaflet lo midió cuando estaba
     oculto, encuadraría contra un tamaño que no es. */
  function encuadrarTablero(mapa, puntos) {
    if (!mapa || !puntos || !puntos.length) return;
    mapa.options.zoomSnap = 0.25;
    mapa.options.zoomDelta = 0.5;
    mapa.invalidateSize(false);
    mapa.fitBounds(L.latLngBounds(puntos), { padding: [56, 56], maxZoom: 7 });
  }

  /* Dos seccionales de la misma ciudad (o del conurbano) caen una arriba de
     la otra y la de abajo no se puede tocar. Si dos burbujas se pisan en
     pantalla, se corren en sentido opuesto hasta quedar separadas por 6 px,
     y una línea fina las une con su punto real, que queda marcado con un
     puntito: la burbuja se movió para poder tocarla, el lugar no.

     `capa` es el layerGroup de las burbujas (hechas con `burbuja`, que les
     anota `_lugar` y `_diametro`). Las guías van en una capa propia que se
     rehace cada vez. Hay que llamarla de nuevo al terminar un zoom: en
     píxeles, la distancia entre dos burbujas cambia con cada nivel. */
  function separarBurbujas(mapa, capa) {
    if (!mapa || !capa) return;
    // Las guías viven en el MAPA y no en la capa: quien llama tira la capa
    // vieja y arma otra en cada filtro, y unas guías colgadas de la vieja
    // quedarían dibujadas para siempre.
    if (mapa._mtGuias) { mapa.removeLayer(mapa._mtGuias); mapa._mtGuias = null; }
    var marcas = capa.getLayers().filter(function (m) { return m._lugar; });
    if (!marcas.length) return;
    var real = marcas.map(function (m) { return mapa.latLngToLayerPoint(m._lugar); });
    var pos = real.map(function (p) { return p.clone(); });
    for (var vuelta = 0; vuelta < 12; vuelta++) {
      var movio = false;
      for (var i = 0; i < marcas.length; i++) {
        for (var j = i + 1; j < marcas.length; j++) {
          var minimo = (marcas[i]._diametro + marcas[j]._diametro) / 2 + 6;
          var dx = pos[j].x - pos[i].x, dy = pos[j].y - pos[i].y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d >= minimo) continue;
          // Encimadas del todo: se abren en diagonal, siempre igual.
          if (d < 0.5) { dx = 1; dy = -0.6; d = Math.sqrt(1.36); }
          var empuje = (minimo - d) / 2;
          var ex = dx / d * empuje, ey = dy / d * empuje;
          pos[i] = L.point(pos[i].x - ex, pos[i].y - ey);
          pos[j] = L.point(pos[j].x + ex, pos[j].y + ey);
          movio = true;
        }
      }
      if (!movio) break;
    }
    var guias = L.layerGroup();
    // La tinta del modelo, no un color de marca: es una línea de lectura.
    var tinta = getComputedStyle(document.documentElement).getPropertyValue("--tinta").trim() || "#1e2b3c";
    marcas.forEach(function (m, k) {
      var corrida = pos[k].distanceTo(real[k]) > 2;
      m.setLatLng(corrida ? mapa.layerPointToLatLng(pos[k]) : m._lugar);
      if (!corrida) return;
      L.polyline([m._lugar, m.getLatLng()], { color: tinta, weight: 1, opacity: 0.55,
        interactive: false }).addTo(guias);
      L.circleMarker(m._lugar, { radius: 2.5, color: tinta, fillColor: tinta, weight: 0, fillOpacity: 0.7,
        interactive: false }).addTo(guias);
    });
    guias.addTo(mapa);
    mapa._mtGuias = guias;
  }

  /* Enlace "cómo llegar" según el teléfono.

     Android entiende el esquema `geo:` y abre la app de mapas que la persona
     tenga puesta por default, no una en particular. iOS no lo soporta y usa
     maps.apple.com. En escritorio no hay app: va Google Maps en el navegador,
     con la URL pública que no pide clave de API. */
  function enlaceComoLlegar(lat, lon, nombre) {
    var ua = navigator.userAgent || "";
    var etiqueta = encodeURIComponent(nombre || "Seccional");
    if (/Android/i.test(ua)) {
      return "geo:" + lat + "," + lon + "?q=" + lat + "," + lon + "(" + etiqueta + ")";
    }
    if (/iPhone|iPad|iPod/i.test(ua)) {
      return "https://maps.apple.com/?daddr=" + lat + "," + lon;
    }
    return "https://www.google.com/maps/search/?api=1&query=" + lat + "," + lon;
  }

  function enlaceVerEnMapa(lat, lon) {
    return "https://www.google.com/maps/search/?api=1&query=" + lat + "," + lon;
  }

  /* Haversine, igual que geo.distancia_km del servidor. Acá se calcula en el
     navegador a propósito: la posición del teléfono NO viaja al servidor. */
  function distanciaKm(lat1, lon1, lat2, lon2) {
    var R = 6371, rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * rad) * Math.cos(lat2 * rad) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return Math.round(R * 2 * Math.asin(Math.sqrt(a)) * 10) / 10;
  }

  /* El teléfono para un enlace wa.me: solo dígitos, con 549 adelante si el
     número vino como se escribe en Argentina. Sin esto, la mitad de los
     WhatsApp de un sindicato abren un chat vacío. */
  function whatsappUrl(numero) {
    var d = String(numero || "").replace(/\D/g, "");
    if (!d) return "";
    if (d.indexOf("54") !== 0) d = "54" + d;
    if (d.indexOf("549") !== 0) d = "549" + d.slice(2);
    return "https://wa.me/" + d;
  }

  global.MapaMT = {
    crear: crear,
    burbuja: burbuja,
    encuadrarTablero: encuadrarTablero,
    separarBurbujas: separarBurbujas,
    colorEscala: colorEscala,
    diametroBurbuja: diametroBurbuja,
    ESCALA: ESCALA,
    enlaceComoLlegar: enlaceComoLlegar,
    enlaceVerEnMapa: enlaceVerEnMapa,
    distanciaKm: distanciaKm,
    whatsappUrl: whatsappUrl,
    ATRIBUCION: ATRIBUCION
  };
})(window);
