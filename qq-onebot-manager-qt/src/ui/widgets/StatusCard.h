#pragma once
#include <QFrame>

class QLabel;

class StatusCard : public QFrame {
    Q_OBJECT
public:
    // iconPath 为状态卡的图标资源路径，传空则不显示图标。
    explicit StatusCard(const QString &title, const QString &iconPath = QString(), QWidget *parent = nullptr);
    void setValue(const QString &value, bool ok, const QString &detail = QString());
    // 用真实头像（如 QQ 登录头像）替换左侧占位图标
    void setIconPixmap(const QPixmap &pixmap);
private:
    void refreshThemeIcon();
    QString m_iconPath;
    bool m_customIcon = false;
    QLabel *m_icon = nullptr;
    QLabel *m_value = nullptr;
    QLabel *m_detail = nullptr;
    QLabel *m_dot = nullptr;
};
