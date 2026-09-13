#pragma once
#include <QFrame>

class QLabel;

class StatusCard : public QFrame {
    Q_OBJECT
public:
    // iconPath 为可替换的占位图标（resources/icons/card-*.svg），传空则不显示图标。
    explicit StatusCard(const QString &title, const QString &iconPath = QString(), QWidget *parent = nullptr);
    void setValue(const QString &value, bool ok);
    // 用真实头像（如 QQ 登录头像）替换左侧占位图标
    void setIconPixmap(const QPixmap &pixmap);
private:
    QLabel *m_icon = nullptr;
    QLabel *m_value = nullptr;
    QLabel *m_dot = nullptr;
};
