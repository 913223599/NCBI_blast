import { describe, it, expect } from 'vitest'
import { reactive, ref } from 'vue'
import { safeDeepClone } from '../clone'

describe('safeDeepClone (Vue Proxy 安全深拷贝)', () => {
  it('能够安全深拷贝嵌套 Vue reactive/ref 对象而不触发 DataCloneError', () => {
    const state = ref([
      reactive({
        id: 'f1',
        shelves: [
          {
            id: 's1',
            boxes: [{ id: 'b1', positions: [{ label: 'A1', occupied: true }] }],
          },
        ],
      }),
    ])

    const cloned = safeDeepClone(state.value)
    expect(cloned).toEqual(state.value)
    expect(cloned[0]).not.toBe(state.value[0])
    cloned[0]!.shelves[0]!.boxes[0]!.positions[0]!.occupied = false
    expect(state.value[0]!.shelves[0]!.boxes[0]!.positions[0]!.occupied).toBe(true)
  })
})
