#include "GroupItemRow.h"
#include "../../core/AvatarCache.h"
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPainter>
#include <QPainterPath>
#include <QPixmap>
#include <QPointer>
#include <QVBoxLayout>

namespace {
QPixmap rounded(const QPixmap &src, int size) {
    QPixmap pm(size, size);
    pm.fill(Qt::transparent);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing);
    QPainterPath path;
    path.addRoundedRect(0, 0, size, size, 7, 7);
    p.setClipPath(path);
    p.drawPixmap(0, 0, src.scaled(size, size, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation));
    return pm;
}
}  // namespace

GroupItemRow::GroupItemRow(const QString &name, const QString &summary, bool dimmed, QWidget *parent)
    : QWidget(parent) {
    // 勾选框由列表绘制在左侧留白处；控件本身不截获鼠标事件
    setAttribute(Qt::WA_TransparentForMouseEvents);
    auto *layout = new QHBoxLayout(this);
    layout->setContentsMargins(34, 5, 6, 5);
    layout->setSpacing(10);
    m_avatar = new QLabel(this);
    m_avatar->setFixedSize(40, 40);
    m_avatar->setAlignment(Qt::AlignCenter);
    layout->addWidget(m_avatar);

    auto *text = new QVBoxLayout;
    text->setContentsMargins(0, 0, 0, 0);
    text->setSpacing(1);
    auto *nameLabel = new QLabel(name, this);
    nameLabel->setObjectName("rowName");
    m_nameLabel = nameLabel;
    auto *summaryLabel = new QLabel(summary, this);
    summaryLabel->setObjectName("rowSummary");
    if (dimmed) {
        // 黑名单群：整行灰显（条目前景色对 itemWidget 内的 QLabel 不生效，需手动设置）
        nameLabel->setStyleSheet("color:#8b96a8;");
        summaryLabel->setStyleSheet("color:#b3aeba;");
    }
    text->addWidget(nameLabel);
    text->addWidget(summaryLabel);
    text->addStretch();
    layout->addLayout(text, 1);
}

void GroupItemRow::setName(const QString &name) {
    if (m_nameLabel) m_nameLabel->setText(name);
}

void GroupItemRow::bind(QListWidget *list, QListWidgetItem *item, const QString &groupId,
                        const QString &name, const QString &summary, bool dimmed) {
    if (!list || !item) return;
    auto *row = new GroupItemRow(name, summary, dimmed, list);
    row->m_avatar->setPixmap(rounded(AvatarCache::placeholder(groupId, 80), 40));
    item->setSizeHint(QSize(0, 52));
    list->setItemWidget(item, row);
    QPointer<QLabel> avatar(row->m_avatar);
    AvatarCache::instance().fetch("group", groupId, [avatar](const QPixmap &pm) {
        if (avatar) avatar->setPixmap(rounded(pm, 40));
    });
}
