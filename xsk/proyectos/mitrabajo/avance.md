---
iteracion: 1
etapa_actual: 8
etapa8: en_curso
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: en_curso
etapa6: hecha
etapa7: hecha
etapa9: pendiente
actualizado: 2026-09-20
---

## Cómo seguir

Bloque 4, lote de fixes chicos cerrado: H-0007 (cabeceras de seguridad,
Parcial — CSP permisiva por el inline), H-0009 (PBKDF2 600k, Solucionado) y
H-0013 (Aceptado — CUIL/CUIT es dato público). Estado: **5 Solucionado, 3
Parcial, 8 Pendiente, 2 Aceptado; bloquean 3**.

Lo que queda, en tres frentes (ya no son fixes sueltos):
1. **Sub-sprint R1** (usuarios de plataforma nominales): cierra H-0002,
   H-0003 y H-0016. Necesita decisiones de producto de SDN.
2. **Perímetro (INF-05)**: cierra H-0008 del todo; depende de dominio propio
   + Cloudflare (faltantes de la etapa 0).
3. Lotes menores: H-0018 (decisión sobre el panel cross-entorno), H-0014
   (deps con CVE) + H-0015 (CI), H-0010 + H-0012 (con un cambio de sesión).
Y la carga (DIS-01/02) + repetir la dinámica contra Pruebas desplegado.
