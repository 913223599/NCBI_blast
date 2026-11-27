import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []

  url: string
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((err: unknown) => void) | null = null
  sent: string[] = []

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.onclose?.()
  }
}

describe('wsClient & bridge event routing', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.resetModules()
    vi.stubGlobal('WebSocket', MockWebSocket)
    delete (window as unknown as Record<string, unknown>).handleBridgeEvent
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('single_result_update 仅触发一次 blast_event 与 onEvent，且其他事件路由唯一', async () => {
    const { bridgeSignals, connectWebSocket, onEvent } = await import('../wsClient')
    const blastSpy = vi.fn()
    const syncSpy = vi.fn()
    const recallSpy = vi.fn()
    const phyloSpy = vi.fn()
    const globalEventSpy = vi.fn()

    const unsubBlast = bridgeSignals.blast_event.connect(blastSpy)
    const _unsubSync = bridgeSignals.sync_event.connect(syncSpy)
    const unsubRecall = bridgeSignals.recall_event.connect(recallSpy)
    const unsubPhylo = bridgeSignals.phylo_event.connect(phyloSpy)
    const unsubGlobal = onEvent(globalEventSpy)

    connectWebSocket()
    const ws = MockWebSocket.instances[0]
    expect(ws).toBeDefined()

    const payload = { task_id: 't1', result: { id: 1 } }
    ws.onmessage?.({ data: JSON.stringify({ type: 'single_result_update', data: payload }) })

    expect(blastSpy).toHaveBeenCalledTimes(1)
    expect(blastSpy).toHaveBeenCalledWith('single_result_update', JSON.stringify(payload))
    expect(globalEventSpy).toHaveBeenCalledTimes(1)
    expect(globalEventSpy).toHaveBeenCalledWith('single_result_update', payload)

    ws.onmessage?.({ data: JSON.stringify({ type: 'data_updated', data: { module: 'strains' } }) })
    expect(syncSpy).toHaveBeenCalledTimes(1)
    expect(syncSpy).toHaveBeenCalledWith({ module: 'strains' })

    ws.onmessage?.({
      data: JSON.stringify({
        type: 'recall_result',
        data: { success: true, message: 'ok', recalled_name: 'S1' },
      }),
    })
    expect(recallSpy).toHaveBeenCalledTimes(1)
    expect(recallSpy).toHaveBeenCalledWith(true, 'ok')

    ws.onmessage?.({ data: JSON.stringify({ type: 'phylo_progress', data: { pct: 50 } }) })
    expect(phyloSpy).toHaveBeenCalledTimes(1)
    expect(phyloSpy).toHaveBeenCalledWith('phylo_progress', { pct: 50 })

    ws.onmessage?.({ data: JSON.stringify({ type: 'translation_done', data: { original: 'A', translated: 'B' } }) })
    expect(blastSpy).toHaveBeenCalledTimes(2)

    // 取消订阅后不再触发
    unsubBlast()
    bridgeSignals.sync_event.disconnect(syncSpy)
    unsubRecall()
    unsubPhylo()
    unsubGlobal()

    ws.onmessage?.({ data: JSON.stringify({ type: 'single_result_update', data: payload }) })
    ws.onmessage?.({ data: JSON.stringify({ type: 'data_updated', data: { module: 'all' } }) })
    expect(blastSpy).toHaveBeenCalledTimes(2)
    expect(syncSpy).toHaveBeenCalledTimes(1)
    expect(globalEventSpy).toHaveBeenCalledTimes(5)
  })

  it('BridgeSignal.connect 防重复注册并支持 disconnect/clear', async () => {
    const { BridgeSignal } = await import('../wsClient')
    const sig = new BridgeSignal()
    const fn = vi.fn()

    const unsub = sig.connect(fn)
    sig.connect(fn)
    sig.emit('hello')
    expect(fn).toHaveBeenCalledTimes(1)

    unsub()
    sig.emit('after-unsub')
    expect(fn).toHaveBeenCalledTimes(1)

    sig.connect(fn)
    sig.clear()
    sig.emit('after-clear')
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('bridge/index.ts onEvent 在未就绪时取消订阅，就绪后不应触发回调', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    const { initBridge, onEvent } = await import('../index')
    const handler = vi.fn()

    const cleanup = onEvent(handler)
    cleanup()

    await initBridge()
    const ws = MockWebSocket.instances[0]
    expect(ws).toBeDefined()
    ws.onmessage?.({ data: JSON.stringify({ type: 'single_result_update', data: { id: 99 } }) })

    expect(handler).not.toHaveBeenCalled()
  })
})
