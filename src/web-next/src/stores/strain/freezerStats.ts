import type { Freezer } from './types'

export function getTotalCabinets(freezer: Freezer): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    total += shelf.cabinets.length
  }
  return total
}

export function getTotalDrawers(freezer: Freezer): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      total += cabinet.drawers.length
    }
  }
  return total
}

export function getTotalBoxes(freezer: Freezer): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      for (const drawer of cabinet.drawers) {
        for (const box of drawer.boxes) {
          total += box.rows * box.cols
        }
      }
    }
  }
  return total
}
