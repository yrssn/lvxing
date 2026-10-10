/**
 * 行数组转 CSV 并下载（带 BOM，Excel 打开中文不乱码）
 * @param {string} filename 文件名
 * @param {string[]} headers 表头
 * @param {Array<Array<any>>} rows 数据行
 */
export function downloadCsv(filename, headers, rows) {
  const escape = (v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [headers.map(escape).join(',')]
  for (const row of rows) lines.push(row.map(escape).join(','))
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
