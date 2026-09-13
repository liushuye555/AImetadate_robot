#include "MainWindow.h"
#include "Strings.h"
#include "theme/ThemeManager.h"
#include <QApplication>
#include <QCloseEvent>
#include <QFrame>
#include <QHBoxLayout>
#include <QIcon>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QPixmap>
#include <QPushButton>
#include <QSettings>
#include <QStackedWidget>
#include <QVBoxLayout>

namespace {
const char *kNavIconFor(const QString &id) {
    if (id == "overview") return ":/icons/nav-overview.svg";
    if (id == "collection") return ":/icons/nav-collection.svg";
    if (id == "relay") return ":/icons/nav-relay.svg";
    if (id == "chat") return ":/icons/nav-chat.svg";
    if (id == "settings") return ":/icons/nav-settings.svg";
    if (id == "logs") return ":/icons/nav-logs.svg";
    if (id == "reports") return ":/icons/nav-reports.svg";
    return ":/icons/app.svg";
}
}  // namespace

MainWindow::MainWindow(const QVector<PageDef> &pages, QWidget *parent)
    : QMainWindow(parent), m_pages(pages) {
    m_nav = new QListWidget(this);
    m_nav->setObjectName("nav");
    m_nav->setFixedWidth(200);
    m_nav->setIconSize(QSize(20, 20));
    m_nav->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);  // 7 个导航项无需滚动

    // 侧边栏品牌区：logo 占位 + 名称（替换 resources/icons/app.svg 即可换标）
    auto *brand = new QFrame(m_nav);
    brand->setObjectName("brand");
    auto *brandLayout = new QHBoxLayout(brand);
    brandLayout->setContentsMargins(14, 12, 10, 12);
    brandLayout->setSpacing(10);
    auto *logo = new QLabel(brand);
    logo->setPixmap(QIcon(":/icons/app.svg").pixmap(30, 30));
    logo->setFixedSize(30, 30);
    auto *brandText = new QVBoxLayout;
    brandText->setContentsMargins(0, 0, 0, 0);
    brandText->setSpacing(0);
    auto *brandName = new QLabel("QQ OneBot", brand);
    brandName->setObjectName("brandName");
    auto *brandSub = new QLabel(Strings::zh("panelName"), brand);
    brandSub->setObjectName("brandSub");
    brandText->addWidget(brandName);
    brandText->addWidget(brandSub);
    brandLayout->addWidget(logo);
    brandLayout->addLayout(brandText, 1);

    // 页头：标题 + 副标题
    auto *header = new QFrame(this);
    header->setObjectName("pageHeader");
    auto *headerLayout = new QVBoxLayout(header);
    headerLayout->setContentsMargins(26, 16, 26, 12);
    headerLayout->setSpacing(2);
    m_header = new QLabel(header);
    m_header->setObjectName("pageTitle");
    m_header->setContentsMargins(0, 0, 0, 0);
    m_subtitle = new QLabel(header);
    m_subtitle->setObjectName("pageSubtitle");
    headerLayout->addWidget(m_header);
    headerLayout->addWidget(m_subtitle);

    m_stack = new QStackedWidget(this);
    auto *rightColumn = new QVBoxLayout;
    rightColumn->setContentsMargins(0, 0, 0, 0);
    rightColumn->setSpacing(0);
    rightColumn->addWidget(header);
    rightColumn->addWidget(m_stack, 1);

    for (const PageDef &page : m_pages) {
        auto *item = new QListWidgetItem(QIcon(kNavIconFor(page.id)), Strings::zh(page.titleKey));
        item->setSizeHint(QSize(0, 42));
        m_nav->addItem(item);
        m_stack->addWidget(page.factory(this));
    }
    m_nav->setCurrentRow(0);
    connect(m_nav, &QListWidget::currentRowChanged, m_stack, &QStackedWidget::setCurrentIndex);
    connect(m_nav, &QListWidget::currentRowChanged, this, [this](int row) {
        if (row >= 0 && row < m_pages.size()) {
            const QString lang = m_lang;
            m_header->setText(Strings::get(m_pages[row].titleKey, lang));
            m_subtitle->setText(Strings::get("sub_" + m_pages[row].id, lang));
        }
    });
    // setCurrentRow 在信号连接前调用，页头需要主动填一次初值
    if (m_nav->currentRow() >= 0) {
        const PageDef &page = m_pages[m_nav->currentRow()];
        m_header->setText(Strings::get(page.titleKey, m_lang));
        m_subtitle->setText(Strings::get("sub_" + page.id, m_lang));
    }

    // 侧栏底部操作区（NapCat 风）：切换主题 + 退出
    auto *actions = new QFrame(this);
    actions->setObjectName("sidebarActions");
    auto *actionsLayout = new QVBoxLayout(actions);
    actionsLayout->setContentsMargins(12, 6, 12, 14);
    actionsLayout->setSpacing(8);
    m_themeButton = new QPushButton(Strings::zh("toggleTheme"), actions);
    m_themeButton->setObjectName("themeButton");
    m_themeButton->setIcon(QIcon(":/icons/card-napcat.svg"));
    auto *quitButton = new QPushButton(Strings::zh("quitApp"), actions);
    quitButton->setObjectName("quitButton");
    actionsLayout->addWidget(m_themeButton);
    actionsLayout->addWidget(quitButton);
    connect(m_themeButton, &QPushButton::clicked, this, [this] {
        ThemeManager::toggle(qApp);
        emit themeToggled(ThemeManager::themeName(ThemeManager::current()));
    });
    connect(quitButton, &QPushButton::clicked, this, [this] { emit trayAction("quit"); });

    auto *content = new QFrame(this);
    content->setObjectName("content");
    auto *layout = new QHBoxLayout(content);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto *navColumn = new QVBoxLayout;
    navColumn->setContentsMargins(0, 0, 0, 0);
    navColumn->setSpacing(0);
    navColumn->addWidget(brand);
    navColumn->addWidget(m_nav, 1);
    // 侧栏左下看板娘（替换 resources/icons/mascot.png 即可换立绘；旧占位为 mascot.svg）
    auto *mascot = new QLabel(this);
    mascot->setObjectName("mascot");
    QPixmap mascotPm(":/icons/mascot.png");
    if (mascotPm.isNull()) mascotPm = QPixmap(":/icons/mascot.svg");
    mascot->setPixmap(mascotPm.scaledToWidth(140, Qt::SmoothTransformation));
    mascot->setAlignment(Qt::AlignBottom | Qt::AlignHCenter);
    mascot->setContentsMargins(0, 0, 0, 4);
    navColumn->addWidget(mascot);
    navColumn->addWidget(actions);
    layout->addLayout(navColumn);
    layout->addLayout(rightColumn, 1);
    setCentralWidget(content);
    setWindowTitle("QQ OneBot 管理器");
    setWindowIcon(QIcon(":/icons/app.svg"));

    const QSettings settings("qq-onebot-manager", "panel");
    const QByteArray geometry = settings.value("window/geometry").toByteArray();
    if (!geometry.isEmpty())
        restoreGeometry(geometry);
    else
        resize(1060, 700);
    setMinimumSize(900, 600);
    setupTray();
}

void MainWindow::setLanguage(const QString &lang) {
    m_lang = lang;
    for (int i = 0; i < m_pages.size(); ++i)
        m_nav->item(i)->setText(Strings::get(m_pages[i].titleKey, lang));
    m_header->setText(Strings::get(m_pages[m_nav->currentRow()].titleKey, lang));
    m_subtitle->setText(Strings::get("sub_" + m_pages[m_nav->currentRow()].id, lang));
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
    connect(m_tray, &QSystemTrayIcon::activated, this, [this](QSystemTrayIcon::ActivationReason reason) {
        if (reason == QSystemTrayIcon::Trigger || reason == QSystemTrayIcon::DoubleClick) {
            showNormal();
            raise();
            activateWindow();
        }
    });
    m_tray->show();
}

void MainWindow::closeEvent(QCloseEvent *event) {
    if (m_tray && m_tray->isVisible()) {
        hide();
        event->ignore();
        return;
    }
    QSettings("qq-onebot-manager", "panel").setValue("window/geometry", saveGeometry());
    event->accept();
}
