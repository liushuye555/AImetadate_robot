#pragma once
#include <QMainWindow>
#include <QSystemTrayIcon>
#include <QVector>

class QListWidget;
class QStackedWidget;
class QLabel;
class QWidget;
class QCloseEvent;

struct PageDef {
    QString id;
    QString titleKey;
    QWidget *(*factory)(QWidget *parent);
};

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(const QVector<PageDef> &pages, QWidget *parent = nullptr);
    void setLanguage(const QString &lang);
    QWidget *pageWidget(const QString &id) const;
    QSystemTrayIcon *trayIcon() const { return m_tray; }
signals:
    void trayAction(const QString &action); // open/start/stop/restart/logs/reports/quit
protected:
    void closeEvent(QCloseEvent *event) override;
private:
    void setupTray();
    QListWidget *m_nav = nullptr;
    QStackedWidget *m_stack = nullptr;
    QLabel *m_header = nullptr;
    QVector<PageDef> m_pages;
    QSystemTrayIcon *m_tray = nullptr;
    QString m_lang = "zh-CN";
};
