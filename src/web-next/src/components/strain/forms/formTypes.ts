export type StrainMetadataFormModel = Record<string, unknown>

export type StrainMetadataFieldValue = string | number | boolean | string[] | null | undefined

export function readFormText(model: StrainMetadataFormModel, key: string): string {
  const val = model[key]
  if (typeof val === 'string' || typeof val === 'number') return String(val)
  return ''
}

export function readFormFlag(model: StrainMetadataFormModel, key: string): boolean {
  return model[key] === true
}
