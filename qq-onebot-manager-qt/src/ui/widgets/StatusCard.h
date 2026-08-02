#pragma once
#include <QFrame>

class QLabel;

class StatusCard : public QFrame {
    Q_OBJECT
public:
    explicit StatusCard(const QString &title, QWidget *parent = nullptr);
    void setValue(const QString &value, bool ok);
private:
    QLabel *m_value = nullptr;
};
