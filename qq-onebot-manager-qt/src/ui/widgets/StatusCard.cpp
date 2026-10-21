#include "StatusCard.h"
#include "../theme/ThemeManager.h"
#include <QHBoxLayout>
#include <QIcon>
#include <QLabel>
#include <QPixmap>
#include <QStyle>
#include <QVBoxLayout>

StatusCard::StatusCard(const QString &title, const QString &iconPath, QWidget *parent)
    : QFrame(parent), m_iconPath(iconPath) {
    setObjectName("card");
    setMinimumHeight(72);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    auto *layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 14, 16, 14);
    layout->setSpacing(12);

    if (!iconPath.isEmpty()) {
        m_icon = new QLabel(this);
        m_icon->setObjectName("cardIcon");
        m_icon->setFixedSize(42, 42);
        m_icon->setScaledContents(false);
        m_icon->setAlignment(Qt::AlignCenter);
        layout->addWidget(m_icon);
        refreshThemeIcon();
        connect(ThemeManager::instance(), &ThemeManager::appearanceChanged,
                this, &StatusCard::refreshThemeIcon);
    }

    auto *text = new QVBoxLayout;
    text->setContentsMargins(0, 0, 0, 0);
    text->setSpacing(2);
    auto *titleRow = new QHBoxLayout;
    titleRow->setContentsMargins(0, 0, 0, 0);
    titleRow->setSpacing(6);
    m_dot = new QLabel(this);
    m_dot->setObjectName("statusDot");
    m_dot->setFixedSize(8, 8);
    auto *titleLabel = new QLabel(title, this);
    titleLabel->setObjectName("cardTitle");
    titleRow->addWidget(m_dot);
    titleRow->addWidget(titleLabel);
    titleRow->addStretch();
    text->addLayout(titleRow);
    m_value = new QLabel("—", this);
    m_value->setObjectName("cardValue");
    m_value->setTextFormat(Qt::PlainText);
    m_value->setWordWrap(true);
    m_value->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    text->addWidget(m_value);
    m_detail = new QLabel(this);
    m_detail->setObjectName("cardDetail");
    m_detail->setTextFormat(Qt::PlainText);
    m_detail->setWordWrap(true);
    m_detail->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    m_detail->hide();
    text->addWidget(m_detail);
    layout->addLayout(text, 1);
}

void StatusCard::setIconPixmap(const QPixmap &pixmap) {
    if (!m_icon || pixmap.isNull()) return;
    m_customIcon = true;
    m_icon->setPixmap(pixmap.scaled(30, 30, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation));
}

void StatusCard::refreshThemeIcon() {
    if (!m_icon || m_customIcon) return;
    const QString prefix = QStringLiteral(":/icons/");
    const QString path = m_iconPath.startsWith(prefix)
        ? ThemeManager::assetPath(m_iconPath.mid(prefix.size())) : m_iconPath;
    m_icon->setPixmap(QIcon(path).pixmap(QSize(36, 36), devicePixelRatioF()));
}

void StatusCard::setValue(const QString &value, bool ok, const QString &detail) {
    m_value->setText(value);
    m_value->setToolTip(detail.isEmpty() ? value : value + "\n" + detail);
    m_detail->setText(detail);
    m_detail->setVisible(!detail.isEmpty());
    m_value->setProperty("state", ok ? "ok" : "bad");
    m_dot->setProperty("state", ok ? "ok" : "bad");
    // 动态属性改变后需要重新 polish 让 QSS 选择器生效
    m_value->style()->unpolish(m_value);
    m_value->style()->polish(m_value);
    m_dot->style()->unpolish(m_dot);
    m_dot->style()->polish(m_dot);
}
