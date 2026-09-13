#pragma once
#include <QWidget>

class QLabel;
class QListWidget;
class QListWidgetItem;

// 原版 QQ 风的群条目：大头像 + 群名/摘要两行文字。
// 整个控件对鼠标透明——勾选、悬停、双击等事件全部交给列表项本身处理。
class GroupItemRow : public QWidget {
    Q_OBJECT
public:
    GroupItemRow(const QString &name, const QString &summary, bool dimmed, QWidget *parent = nullptr);
    // 扫描回来后更新群名显示（名称行；摘要行不动）
    void setName(const QString &name);
    // 组装条目：占位头像立即显示，真实群头像异步回填（磁盘缓存）
    static void bind(QListWidget *list, QListWidgetItem *item, const QString &groupId,
                     const QString &name, const QString &summary, bool dimmed = false);
private:
    QLabel *m_avatar = nullptr;
    QLabel *m_nameLabel = nullptr;
};
