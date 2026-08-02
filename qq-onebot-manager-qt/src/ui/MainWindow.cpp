#include "MainWindow.h"
#include "Strings.h"
#include <QCloseEvent>
#include <QIcon>
#include <QListWidget>
#include <QMenu>
#include <QStackedWidget>
#include <QHBoxLayout>
#include <QFrame>

MainWindow::MainWindow(const QVector<PageDef> &pages, QWidget *parent)
    : QMainWindow(parent), m_pages(pages) {
    m_nav = new QListWidget(this);
    m_nav->setObjectName("nav");
    m_nav->setFixedWidth(180);
    m_stack = new QStackedWidget(this);

    for (const PageDef &page : m_pages) {
        m_nav->addItem(Strings::zh(page.titleKey));
        m_stack->addWidget(page.factory(this));
    }
    m_nav->setCurrentRow(0);
    connect(m_nav, &QListWidget::currentRowChanged, m_stack, &QStackedWidget::setCurrentIndex);

    auto *content = new QFrame(this);
    content->setObjectName("content");
    auto *layout = new QHBoxLayout(content);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addWidget(m_nav);
    layout->addWidget(m_stack, 1);
    setCentralWidget(content);
    resize(960, 640);
    setWindowTitle("QQ OneBot 管理器");
    setupTray();
}

void MainWindow::setLanguage(const QString &lang) {
    m_lang = lang;
    for (int i = 0; i < m_pages.size(); ++i)
        m_nav->item(i)->setText(Strings::get(m_pages[i].titleKey, lang));
}

QWidget *MainWindow::pageWidget(const QString &id) const {
    for (int i = 0; i < m_pages.size(); ++i)
        if (m_pages[i].id == id) return m_stack->widget(i);
    return nullptr;
}

void MainWindow::setupTray() {
    m_tray = new QSystemTrayIcon(QIcon(":/icons/app.svg"), this);
    auto *menu = new QMenu(this);
    menu->addAction(Strings::zh("overview"), this, [this] { showNormal(); raise(); activateWindow(); });
    menu->addSeparator();
    menu->addAction(Strings::zh("start"), this, [this] { emit trayAction("start"); });
    menu->addAction(Strings::zh("stop"), this, [this] { emit trayAction("stop"); });
    menu->addAction(Strings::zh("restart"), this, [this] { emit trayAction("restart"); });
    menu->addSeparator();
    menu->addAction(Strings::zh("openLogs"), this, [this] { emit trayAction("logs"); });
    menu->addAction(Strings::zh("openReports"), this, [this] { emit trayAction("reports"); });
    menu->addSeparator();
    menu->addAction(Strings::zh("quit"), this, [this] { emit trayAction("quit"); });
    m_tray->setContextMenu(menu);
    m_tray->show();
}

void MainWindow::closeEvent(QCloseEvent *event) {
    if (m_tray && m_tray->isVisible()) {
        hide();
        event->ignore();
    } else {
        event->accept();
    }
}
