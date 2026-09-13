#include "StatusCard.h"
#include <QHBoxLayout>
#include <QLabel>
#include <QPixmap>
#include <QStyle>
#include <QVBoxLayout>

StatusCard::StatusCard(const QString &title, const QString &iconPath, QWidget *parent) : QFrame(parent) {
    setObjectName("card");
    auto *layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 14, 16, 14);
    layout->setSpacing(12);

    if (!iconPath.isEmpty()) {
        m_icon = new QLabel(this);
        m_icon->setObjectName("cardIcon");
        m_icon->setPixmap(QPixmap(iconPath));
        m_icon->setFixedSize(34, 34);
        m_icon->setScaledContents(false);
        m_icon->setAlignment(Qt::AlignCenter);
        layout->addWidget(m_icon);
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
    text->addWidget(m_value);
    layout->addLayout(text, 1);
}

void StatusCard::setIconPixmap(const QPixmap &pixmap) {
    if (!m_icon || pixmap.isNull()) return;
    m_icon->setPixmap(pixmap.scaled(30, 30, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation));
}

void StatusCard::setValue(const QString &value, bool ok) {
    m_value->setText(value);
    m_value->setProperty("state", ok ? "ok" : "bad");
    m_dot->setProperty("state", ok ? "ok" : "bad");
    // 动态属性改变后需要重新 polish 让 QSS 选择器生效
    m_value->style()->unpolish(m_value);
    m_value->style()->polish(m_value);
    m_dot->style()->unpolish(m_dot);
    m_dot->style()->polish(m_dot);
}
