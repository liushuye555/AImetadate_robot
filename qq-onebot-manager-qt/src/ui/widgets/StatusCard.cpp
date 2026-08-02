#include "StatusCard.h"
#include <QLabel>
#include <QVBoxLayout>

StatusCard::StatusCard(const QString &title, QWidget *parent) : QFrame(parent) {
    setObjectName("card");
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(14, 12, 14, 12);
    auto *titleLabel = new QLabel(title, this);
    titleLabel->setObjectName("muted");
    m_value = new QLabel("—", this);
    m_value->setStyleSheet("font-size:16px;font-weight:600;");
    layout->addWidget(titleLabel);
    layout->addWidget(m_value);
}

void StatusCard::setValue(const QString &value, bool ok) {
    m_value->setText(value);
    m_value->setStyleSheet(ok
        ? "font-size:16px;font-weight:600;color:#2d825d;"
        : "font-size:16px;font-weight:600;color:#b53b49;");
}
