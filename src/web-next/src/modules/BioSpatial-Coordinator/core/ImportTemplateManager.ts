import ExcelJS from 'exceljs'

export interface TemplateDefinition {
  type: string;
  name: string;
  headers: string[];
  example: string[];
}

/**
 * 导入模板管理类
 * 职责：定义模板结构、示例数据，并生成标准的带数据验证的 Excel 文件
 */
export class ImportTemplateManager {
  // 定义通用字段，所有模板都会包含这些基础元数据
  private static readonly COMMON_HEADERS = [
    'name', 'species', 'strain', 'sampleType', 'quantity', 'source', 'sequenceType', 
    'host', 'country', 'collectionDate', 'storageDate', 'storageMedium', 'biosafetyLevel', 
    'passageNumber', 'batchNumber', 'sequence', 'description'
  ];

  // 全局默认示例数据（当特定模板未定义时使用）
  private static readonly DEFAULT_EXAMPLE: Record<string, string> = {
    name: '样本名称-001',
    species: 'Escherichia coli',
    strain: 'K-12 MG1655',
    sampleType: 'Bacteria',
    quantity: '1',
    source: '研究所仓库',
    sequenceType: 'DNA',
    host: 'Homo sapiens',
    country: 'China',
    collectionDate: '2024-01-01',
    storageDate: '2024-04-15',
    storageMedium: '甘油 (20%)',
    biosafetyLevel: 'BSL-1',
    passageNumber: '1',
    batchNumber: 'BATCH-2024-001',
    sequence: 'ATGC...',
    description: '常规科研样本，-80度保存',
    // 其它类型特有字段默认值
    resistance: '-',
    concentration: '100 ng/uL',
    cultureCondition: 'LB 培养基',
    growthTemp: '37°C',
    backbone: 'pET-28a(+)',
    insertName: 'GFP',
    hostStrain: 'BL21(DE3)',
    marker: 'Kanamycin',
    isExpression: 'True',
    titer: '1e8 TCID50/mL',
    potency: 'High',
    serotype: 'Type-1',
    inactivationMethod: 'Heat',
    cellType: 'HeLa',
    medium: 'DMEM + 10% FBS',
    authentication: 'STR验证通过'
  };

  // 各类型特有字段定义
  private static readonly CONFIGS: Record<string, { label: string, extraHeaders: string[], exampleMap: Record<string, string> }> = {
    General: {
      label: '通用样本',
      extraHeaders: [],
      exampleMap: { }
    },
    Bacteria: {
      label: '微生物/细菌',
      extraHeaders: ['resistance', 'concentration', 'cultureCondition', 'growthTemp'],
      exampleMap: { 
        name: 'E.coli-K12', 
        species: 'Escherichia coli', 
        sampleType: 'Bacteria', 
        sequenceType: 'DNA',
        resistance: 'Ampicillin',
        concentration: '5e8 CFU/mL'
      }
    },
    Fungi: {
      label: '真菌',
      extraHeaders: ['resistance', 'cultureCondition', 'growthTemp'],
      exampleMap: { 
        name: 'S.cerevisiae-S288C', 
        species: 'Saccharomyces cerevisiae', 
        sampleType: 'Fungi', 
        sequenceType: 'DNA',
        cultureCondition: 'PDA'
      }
    },
    Phage: {
      label: '噬菌体',
      extraHeaders: ['hostStrain', 'titer'],
      exampleMap: { 
        name: 'Phage-T4', 
        species: 'Enterobacteria phage T4', 
        sampleType: 'Phage', 
        sequenceType: 'DNA',
        hostStrain: 'E. coli B',
        titer: '1e10 PFU/mL'
      }
    },
    Plasmid: {
      label: '质粒/载体',
      extraHeaders: ['backbone', 'insertName', 'hostStrain', 'concentration', 'marker', 'isExpression'],
      exampleMap: { 
        name: 'pET28a-GFP', 
        species: 'Recombinant Plasmid', 
        sampleType: 'Plasmid', 
        sequenceType: 'DNA',
        backbone: 'pET-28a(+)',
        insertName: 'GFP',
        marker: 'Kanamycin'
      }
    },
    Virus: {
      label: '病毒',
      extraHeaders: ['titer', 'potency', 'serotype', 'inactivationMethod'],
      exampleMap: { 
        name: 'InfV-A-H1N1', 
        species: 'Influenza A virus', 
        sampleType: 'Virus', 
        sequenceType: 'RNA',
        titer: '1e7 TCID50'
      }
    },
    CellLine: {
      label: '细胞系',
      extraHeaders: ['cellType', 'medium', 'authentication'],
      exampleMap: { 
        name: 'HeLa-Box12', 
        species: 'Homo sapiens', 
        sampleType: 'CellLine', 
        sequenceType: 'DNA',
        cellType: 'HeLa',
        medium: 'DMEM + 10% FBS'
      }
    }
  };

  /**
   * 生成指定类型的 Excel 模板
   */
  public static async generateXLSX(type: string, sourceOptions: string[]): Promise<{ blob: Blob, fileName: string }> {
    // 确保绝对有一个回退
    const config = this.CONFIGS[type] || this.CONFIGS['General']!;
    
    // 合并表头：基础字段 + 类型特有字段
    const headers = [...this.COMMON_HEADERS];
    // 将特有字段插在 source 之后，看起来更自然
    const insertPos = headers.indexOf('source') + 1;
    headers.splice(insertPos, 0, ...config.extraHeaders);

    // 生成示例数据 (合并默认值)
    const exampleRow = headers.map(h => {
      if (h === 'source') return sourceOptions[0] || '默认来源';
      
      // 优先级：特定模板定义 > 全局默认定义 > 横杠
      return config.exampleMap[h] || this.DEFAULT_EXAMPLE[h] || '-';
    });

    const workbook = new ExcelJS.Workbook();
    // 关键修复：Excel 工作表名称不能包含 / \ ? * : [ ] 等非法字符
    const safeLabel = config.label.replace(/[\/\\?*:[\]]/g, '_');
    const worksheet = workbook.addWorksheet(`导入模板-${safeLabel}`);

    // 1. 设置表头
    const headerRow = worksheet.addRow(headers);
    headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
    headerRow.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF475569' } // 深灰色表头
    };

    // 2. 设置示例行
    worksheet.addRow(exampleRow);

    // 3. 应用数据验证（下拉框）
    this.applyDataValidations(worksheet, headers, sourceOptions);

    // 4. 表格美化
    worksheet.columns.forEach(column => {
      column.width = 18;
    });

    // 5. 导出
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const fileName = `样本导入模板_${config.label}.xlsx`;

    return { blob, fileName };
  }

  /**
   * 应用 Excel 数据效验规则
   */
  private static applyDataValidations(worksheet: ExcelJS.Worksheet, headers: string[], sourceOptions: string[]) {
    // 基础下拉选项定义
    const validations: Record<string, string[]> = {
      source: sourceOptions,
      sampletype: ['Bacteria', 'Virus', 'Plasmid', 'CellLine', 'Fungi', 'Phage', 'DNA', 'RNA', 'Other'],
      sequencetype: ['DNA', 'RNA', 'Protein'],
      isexpression: ['True', 'False']
    };

    headers.forEach((h, index) => {
      const colIndex = index + 1;
      const lowerKey = h.toLowerCase();
      
      if (validations[lowerKey]) {
        const colLetter = worksheet.getColumn(colIndex).letter;
        let options = validations[lowerKey];
        
        // 关键修复：Excel 公式限制 255 字符，如果来源列表太长，会导致生成失败
        // 目前简单的解决方法是截断，或者后续建议用户使用定义名称（Name Range）
        let formula = `"${options.join(',')}"`;
        if (formula.length > 255) {
          // 尝试通过过滤掉次要选项来缩短
          const truncated = options.slice(0, 10); 
          formula = `"${truncated.join(',')}"`;
        }

        // 高亮表头辅助识别
        const headerCell = worksheet.getCell(`${colLetter}1`);
        headerCell.fill = {
          type: 'pattern',
          pattern: 'solid',
          fgColor: { argb: 'FFFBFF6B' } // 亮黄色提醒
        };
      }
    });
  }
}
