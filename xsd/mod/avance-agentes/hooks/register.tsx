import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Agente, Plan } from '../types'

const PANE = 'avance'
const TITULO = 'Avance'
// El plan lo escribe la sesión principal (XSD) en `xsd-trabajo/avance.json`,
// en la raíz del proyecto; el panel lo relee cada 4 s.
const PLAN_RELATIVO = 'xsd-trabajo/avance.json'
const PRINCIPAL = 'principal'

const agentes = atom({ plugin: 'avance-agentes', key: 'agentes' } as const, {} as Record<string, Agente>, { shape: 'agentes-1' })
const plan = atom({ plugin: 'avance-agentes', key: 'plan' } as const, null as Plan | null, { shape: 'plan-1' })

const corto = (s: string, n = 70) => (s.length > n ? s.slice(0, n - 1) + '…' : s)
const base = (p: unknown) => (typeof p === 'string' ? p.split('/').slice(-2).join('/') : '')

// Qué está haciendo, en una línea, a partir de la herramienta que usa.
function resumen(e: Record<string, unknown>): string {
  const t = String(e.tool ?? '')
  if (t === 'Bash') return 'Bash: ' + corto(String(e.description || e.command || ''), 60)
  if (t === 'Edit' || t === 'Write' || t === 'Read') return t + ' ' + base(e.file_path)
  if (t === 'Grep') return 'Busca ' + corto(String(e.pattern ?? ''), 50)
  if (t === 'Glob') return 'Lista ' + corto(String(e.pattern ?? ''), 50)
  if (t === 'Agent') return 'Lanza agente: ' + corto(String(e.description ?? ''), 50)
  return t
}

function minutos(desde: number, hasta: number): string {
  const m = Math.max(0, Math.round((hasta - desde) / 60000))
  return m < 1 ? 'recién' : `${m} min`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'avance', description: 'Abre el panel de avance del plan y de los agentes' })
    void $.ui.open({ id: PANE, title: TITULO })
    const PLAN = (await $.session.root()) + '/' + PLAN_RELATIVO
    const leer = async () => {
      try {
        const texto = await $.fs.read(PLAN)
        const nuevo = JSON.parse(String(texto)) as Plan
        const viejo = await read($, plan)
        if (!viejo || viejo.actualizado !== nuevo.actualizado) await update($, plan, () => nuevo)
      } catch {
        // sin plan todavía: el panel lo dice
      }
    }
    void leer()
    $.clock.every(4000, leer)
    return next(e)
  })

  on('command.run', { command: 'avance' }, async $ => {
    await $.ui.open({ id: PANE, title: TITULO })
    return { text: 'Panel de avance abierto.' }
  })

  on('agent.spawn', async ($, e, next) => {
    const r = await next(e)
    if (r.agentId) {
      const id = r.agentId
      const ahora = await $.clock.now()
      await update($, agentes, a => ({
        ...a,
        [id]: { id, nombre: corto(e.description || e.subagentType, 48), inicio: ahora, ultimo: 'arrancando', pasos: 0, estado: 'trabaja' },
      }))
    }
    return r
  })

  on('tool.call', async ($, e, next) => {
    const id = e.agentId ?? PRINCIPAL
    const linea = resumen(e as unknown as Record<string, unknown>)
    const ahora = await $.clock.now()
    await update($, agentes, a => {
      const prev = a[id] ?? { id, nombre: id === PRINCIPAL ? 'Sesión principal' : 'Agente', inicio: ahora, ultimo: '', pasos: 0, estado: 'trabaja' as const }
      return { ...a, [id]: { ...prev, ultimo: linea, pasos: prev.pasos + 1, estado: 'trabaja' } }
    })
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const id = e.agentId
    if (id) {
      const ahora = await $.clock.now()
      await update($, agentes, a =>
        a[id] ? { ...a, [id]: { ...a[id], estado: e.isAborted ? 'cortado' : 'listo', fin: ahora } } : a,
      )
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const p = await read($, plan)
    const lista = Object.values(await read($, agentes))
    const ahora = await $.clock.now()
    const principal = lista.find(x => x.id === PRINCIPAL)
    const otros = lista.filter(x => x.id !== PRINCIPAL).sort((a, b) =>
      (a.estado === 'trabaja' ? 0 : 1) - (b.estado === 'trabaja' ? 0 : 1) || b.inicio - a.inicio)
    const hechos = p ? p.bloques.filter(b => b.estado === 'hecho').length : 0
    const marca = (s: string) => (s === 'hecho' ? '✓' : s === 'en_curso' ? '▶' : '·')
    const icono = (s: string) => (s === 'trabaja' ? '●' : s === 'listo' ? '✓' : '✕')

    return (
      <Box flexDirection="column">
        <Text bold>{p ? p.titulo : 'Plan'}</Text>
        {p ? (
          <Text dimColor>{`${hechos} de ${p.bloques.length} bloques hechos`}</Text>
        ) : (
          <Text dimColor>Todavía no hay plan cargado.</Text>
        )}
        {p && p.bloques.map(b => (
          <Text bold={b.estado === 'en_curso'} dimColor={b.estado === 'hecho'}>
            {`${marca(b.estado)} ${b.nombre}${b.detalle ? ' — ' + corto(b.detalle, 60) : ''}`}
          </Text>
        ))}
        {p && p.nota ? <Text dimColor>{corto(p.nota, 120)}</Text> : null}
        <Text> </Text>
        <Text bold>Agentes</Text>
        {principal ? <Text>{`● Sesión principal · ${principal.pasos} pasos`}</Text> : null}
        {principal ? <Text dimColor>{`   ${corto(principal.ultimo, 72)}`}</Text> : null}
        {otros.length === 0 ? <Text dimColor>Ningún agente lanzado todavía.</Text> : null}
        {otros.map(a => (
          <Box flexDirection="column">
            <Text bold={a.estado === 'trabaja'} dimColor={a.estado !== 'trabaja'}>
              {`${icono(a.estado)} ${a.nombre} · ${minutos(a.inicio, a.fin ?? ahora)} · ${a.pasos} pasos`}
            </Text>
            {a.estado === 'trabaja' ? <Text dimColor>{`   ${corto(a.ultimo, 72)}`}</Text> : null}
          </Box>
        ))}
      </Box>
    )
  })
}
