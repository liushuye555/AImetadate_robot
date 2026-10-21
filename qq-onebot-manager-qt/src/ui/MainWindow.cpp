#include "MainWindow.h"
#include "WindowActivation.h"
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
#include <QResizeEvent>
#include <QSettings>
#include <QStackedWidget>
#include <QVBoxLayout>

namespace {
const char *kNavIconFor(const QString &id) {
    if (id == "overview") return "nav-overview.png";
    if (id == "collection") return "nav-collection.png";
    if (id == "relay") return "nav-relay.png";
    if (id == "chat") return "nav-chat.png";
    if (id == "settings") return "nav-settings.png";
    if (id == "logs") return "nav-logs.png";
    if (id == "reports") return "nav-reports.png";
    return "app.png";
}
}  // namespace

MainWindow::MainWindow(const QVector<PageDef> &pages, QWidget *parent)
    : QMainWindow(parent), m_pages(pages) {
    m_nav = new QListWidget(this);
    m_nav->setObjectName("nav");
    m_nav->setFixedWidth(200);
    m_nav->setIconSize(QSize(32, 32));
    m_nav->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);  // 7 个导航项无需滚动

    // 侧边栏品牌区：随主题切换的 Q 版头像 + 名称。
    auto *brand = new QFrame(m_nav);
    brand->setObjectName("brand");
    auto *brandLayout = new QHBoxLayout(brand);
    brandLayout->setContentsMargins(14, 12, 10, 12);
    brandLayout->setSpacing(10);
    auto *logo = new QLabel(brand);
    m_logo = logo;
    logo->setObjectName("brandLogo");
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
        QIcon pageIcon(ThemeManager::assetPath(kNavIconFor(page.id)));
        // Keep the full-resolution portrait in both modes, including fractional DPI.
        pageIcon.addPixmap(QPixmap(ThemeManager::assetPath(kNavIconFor(page.id))), QIcon::Selected);
        auto *item = new QListWidgetItem(pageIcon, Strings::zh(page.titleKey));
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
    m_themeButton->setIcon(QIcon(ThemeManager::assetPath("action-theme.png")));
    m_themeButton->setIconSize(QSize(28, 28));
    auto *quitButton = new QPushButton(Strings::zh("quitApp"), actions);
    m_quitButton = quitButton;
    quitButton->setObjectName("quitButton");
    quitButton->setIcon(QIcon(ThemeManager::assetPath("action-quit.png")));
    quitButton->setIconSize(QSize(28, 28));
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
    // 透明底 Q 版角色；SVG 在图片不可用时提供同风格后备图。
    m_mascot = new QLabel(this);
    m_mascot->setObjectName("mascot");
    m_mascotSource = QPixmap(ThemeManager::assetPath("mascot.png"));
    if (m_mascotSource.isNull()) m_mascotSource = QPixmap(":/icons/mascot.svg");
    m_mascot->setPixmap(m_mascotSource.scaled(140, 176, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    m_mascot->setAlignment(Qt::AlignBottom | Qt::AlignHCenter);
    m_mascot->setContentsMargins(0, 0, 0, 4);
    navColumn->addWidget(m_mascot);
    navColumn->addWidget(actions);
    layout->addLayout(navColumn);
    layout->addLayout(rightColumn, 1);
    setCentralWidget(content);
    setWindowTitle("QQ OneBot 管理器");
    setWindowIcon(QIcon(ThemeManager::assetPath("app.png")));

    const QSettings settings("qq-onebot-manager", "panel");
    const QByteArray geometry = settings.value("window/geometry").toByteArray();
    if (!geometry.isEmpty())
        restoreGeometry(geometry);
    else
        resize(1060, 700);
    setMinimumSize(900, 600);
    setupTray();
    connect(ThemeManager::instance(), &ThemeManager::appearanceChanged,
            this, &MainWindow::refreshThemeAssets);
    refreshThemeAssets();
}

void MainWindow::refreshThemeAssets() {
    const QIcon appIcon(ThemeManager::assetPath("app.png"));
    setWindowIcon(appIcon);
    m_logo->setPixmap(appIcon.pixmap(QSize(30, 30), devicePixelRatioF()));
    for (int i = 0; i < m_pages.size(); ++i) {
        QIcon icon(ThemeManager::assetPath(kNavIconFor(m_pages[i].id)));
        icon.addPixmap(QPixmap(ThemeManager::assetPath(kNavIconFor(m_pages[i].id))), QIcon::Selected);
        m_nav->item(i)->setIcon(icon);
    }
    m_themeButton->setIcon(QIcon(ThemeManager::assetPath("action-theme.png")));
    m_quitButton->setIcon(QIcon(ThemeManager::assetPath("action-quit.png")));
    m_mascotSource = QPixmap(ThemeManager::assetPath("mascot.png"));
    if (m_mascotSource.isNull()) m_mascotSource = QPixmap(":/icons/mascot.svg");
    resizeMascot();
    if (m_tray) m_tray->setIcon(QIcon(ThemeManager::assetPath("app.ico")));
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
    m_tray = new QSystemTrayIcon(QIcon(ThemeManager::assetPath("app.ico")), this);
    m_tray->setToolTip(windowTitle());
    auto *menu = new QMenu(this);
    menu->addAction(Strings::zh("overview"), this, &MainWindow::showAndActivate);
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
            showAndActivate();
        }
    });
    m_tray->show();
}

void MainWindow::showAndActivate() {
    showAndActivateWindow(this);
}

void MainWindow::resizeEvent(QResizeEvent *event) {
    QMainWindow::resizeEvent(event);
    resizeMascot();
}

void MainWindow::resizeMascot() {
    if (!m_mascot || m_mascotSource.isNull()) return;
    const auto *brand = findChild<QFrame *>("brand");
    const auto *actions = findChild<QFrame *>("sidebarActions");
    if (!brand || !actions) return;
    // Reserve all seven navigation rows; shrink the decorative character first.
    const int reserved = m_nav->count() * 42 + brand->sizeHint().height()
        + actions->sizeHint().height() + 24;
    const int mascotHeight = qBound(80, height() - reserved, 176);
    m_mascot->setPixmap(m_mascotSource.scaled(140, mascotHeight, Qt::KeepAspectRatio,
                                           Qt::SmoothTransformation));
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
