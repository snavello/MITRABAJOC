Corrida de ráfagas con 200 lectores lanzada como **Job de Render** (job-dblter6c6qcc73f9f0lg,
01:10 a 01:27 UTC del 2026-11-05), generador adentro del mismo centro de datos y sin el proxy
de la sesión de Code, para descartar que la cola la pusiera el generador. Configuración:
web 4c-8g × 2 instancias (4 workers c/u), base 4c-16g, cupo 15+10, listas sin imágenes.
k6 con GOMEMLIMIT=1500MiB (el primer intento, job-dblt5fh42hec73ea6lf0, murió por memoria a
los 13 min: 8 GiB; con el tope, 240 MB). Resultado (del log del Job):

  ráfaga  2:   26 subidas, p50 11.6 s, p95 21.4 s, error 3.85 %
  ráfaga  5:   82 subidas, p50 8.7 s, p95 16.7 s, error 2.44 %
  ráfaga 10:  150 subidas, p50 8.8 s, p95 20.0 s, error 1.33 %
  ráfaga 20:  287 subidas, p50 9.7 s, p95 21.8 s, error 1.74 %
  ráfaga 40:  491 subidas, p50 12.3 s, p95 26.1 s, error 0.00 %
  lectores p95 17.7 s, falla 4.37 %   (p50 633 ms, p99 27,4 s)
  500: 0   503: 1197   E-RECIBO-04: 0
  login p50 7078 p95 22272 · home p50 937 p95 24073 · tu_dia p50 354 p95 11504
  novedades p50 462 p95 14086 · recibo p50 560 p95 14831

Igual que la corrida 2c hecha desde la sesión: el generador no es la causa de la cola.
