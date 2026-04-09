"""
结果数据模型
用于 QTableView 的高性能数据模型
"""

from PyQt6.QtGui import QColor

class ResultItem:
    """树形结构节点"""
    def __init__(self, data, parent=None):
        self.parent_item = parent
        self.item_data = data # [Name, Status, Time]
        self.child_items = []
        self.result_data = None # 关联的详细结果数据

    def append_child(self, item):
        self.child_items.append(item)

    def child(self, row):
        if 0 <= row < len(self.child_items):
            return self.child_items[row]
        return None

    def child_count(self):
        return len(self.child_items)

    def column_count(self):
        return len(self.item_data)

    def data(self, column):
        if 0 <= column < len(self.item_data):
            return self.item_data[column]
        return None

    def row(self):
        if self.parent_item:
            return self.parent_item.child_items.index(self)
        return 0

    def parent(self):
        return self.parent_item

class ResultTreeModel(QAbstractItemModel):
    """自定义树形模型"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_item = ResultItem(["文件名/序列/结果", "状态", "耗时"])
        self.headers = ["文件名/序列/结果", "状态", "耗时"]

    def columnCount(self, parent=QModelIndex()):
        return 3

    def data(self, index, role):
        if not index.isValid():
            return None

        item = index.internalPointer()

        if role == Qt.ItemDataRole.DisplayRole:
            return item.data(index.column())
        
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            status = item.data(1)
            if status == "成功":
                return QColor("#67C23A")
            elif status == "失败":
                return QColor("#F56C6C")
            elif status == "处理中":
                return QColor("#409EFF")

        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        child_item = index.internalPointer()
        parent_item = child_item.parent()

        if parent_item == self.root_item:
            return QModelIndex()

        return self.createIndex(parent_item.row(), 0, parent_item)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()

        return parent_item.child_count()

    # --- 自定义方法 ---

    def add_file_node(self, file_name, status="待处理"):
        """添加文件节点"""
        self.beginInsertRows(QModelIndex(), self.root_item.child_count(), self.root_item.child_count())
        item = ResultItem([file_name, status, ""], self.root_item)
        self.root_item.append_child(item)
        self.endInsertRows()
        return item

    def clear(self):
        self.beginResetModel()
        self.root_item = ResultItem(self.headers)
        self.endResetModel()
