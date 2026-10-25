export type Agente = {
  id: string
  nombre: string
  inicio: number
  ultimo: string
  pasos: number
  estado: 'trabaja' | 'listo' | 'cortado'
  fin?: number
}
export type Bloque = { id: string; nombre: string; estado: 'pendiente' | 'en_curso' | 'hecho'; detalle?: string }
export type Plan = { titulo: string; actualizado: string; bloques: Bloque[]; nota?: string }

declare module 'claude-code' {
  interface PluginState {
    'avance-agentes': { agentes: Shaped<Record<string, Agente>>; plan: Shaped<Plan | null> }
  }
}
