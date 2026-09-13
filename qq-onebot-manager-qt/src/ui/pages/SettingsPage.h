#pragma once
#include <QWidget>
#include <QJsonArray>
#include <QJsonObject>
#include <QVariant>
#include <QHash>
#include <QMap>

class QVBoxLayout;
class QPushButton;
class QLabel;
class QComboBox;
class QCheckBox;
class QPlainTextEdit;
class QListWidget;
class QStackedWidget;

class SettingsPage : public QWidget {
    Q_OBJECT
public:
    explicit SettingsPage(QWidget *parent = nullptr);
    void setSchema(const QVariant &schema);
    void setSavedMessage(const QString &text);
    void showError(const QString &text);
    // 侧栏切换主题后同步下拉框（不触发 themeChanged 回环）
    void setTheme(const QString &theme);
    QComboBox *languageCombo() const { return m_language; }
    QComboBox *themeCombo() const { return m_theme; }
    QCheckBox *autoStartBox() const { return m_autoStart; }
    QCheckBox *notificationsBox() const { return m_notifications; }
signals:
    void saveRequested(QJsonObject patch);
    void webuiRequested();
    void providersChanged(const QJsonObject &providers, const QString &secretKeyEnv, const QString &secretValue);
    void languageChanged(const QString &lang);
    void themeChanged(const QString &theme);
    void autoStartToggled(bool enabled);
    void notificationsToggled(bool enabled);
protected:
    bool eventFilter(QObject *obj, QEvent *event) override;
private:
    QJsonObject buildPatch() const;
    QString validationError() const;
    QVBoxLayout *sectionLayout(const QString &section);
    QWidget *buildGeneralTab();
    QWidget *buildProviderEditor();
    QJsonObject buildProvidersObject() const;
    void openProviderDialog(const QString &editName);
    void rebuildProviderList();
    void markDirty();
    void installWheelGuard(QWidget *widget);
    QListWidget *m_subnav = nullptr;
    QStackedWidget *m_stack = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    QHash<QString, QWidget *> m_fields;
    QMap<QString, QVBoxLayout *> m_tabLayouts;
    QComboBox *m_language = nullptr;
    QComboBox *m_theme = nullptr;
    QString m_pendingTheme;
    QCheckBox *m_autoStart = nullptr;
    QCheckBox *m_notifications = nullptr;
    QListWidget *m_providerList = nullptr;
    QMap<QString, QJsonObject> m_providerMap;
    bool m_dirty = false;
};
