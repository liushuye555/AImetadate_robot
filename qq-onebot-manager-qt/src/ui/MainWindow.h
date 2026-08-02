#pragma once
#include <QMainWindow>
#include <QVector>

class QListWidget;
class QStackedWidget;
class QWidget;

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
private:
    QListWidget *m_nav = nullptr;
    QStackedWidget *m_stack = nullptr;
    QVector<PageDef> m_pages;
    QString m_lang = "zh-CN";
};
