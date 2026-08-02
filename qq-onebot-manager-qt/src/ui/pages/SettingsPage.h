#pragma once
#include <QWidget>
#include <QJsonObject>
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
    QComboBox *languageCombo() const { return m_language; }
    QComboBox *themeCombo() const { return m_theme; }
    QCheckBox *autoStartBox() const { return m_autoStart; }
    QCheckBox *notificationsBox() const { return m_notifications; }
signals:
    void saveRequested(QJsonObject patch);
    void providersChanged(const QJsonObject &providers, const QString &secretKeyEnv, const QString &secretValue);
    void languageChanged(const QString &lang);
    void themeChanged(const QString &theme);
    void autoStartToggled(bool enabled);
    void notificationsToggled(bool enabled);
protected:
    bool eventFilter(QObject *obj, QEvent *event) override;
private:
    QJsonObject buildPatch() const;
    QVBoxLayout *sectionLayout(const QString &section);
    QWidget *buildGeneralTab();
    QWidget *buildProviderEditor();
    QWidget *buildCollectionEditor();
    QJsonObject buildProvidersObject() const;
    QJsonObject buildCollectionObject() const;
    void openProviderDialog(const QString &editName);
    void openCollectionDialog(const QString &editGroup);
    void rebuildProviderList();
    void rebuildCollectionList();
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
    QCheckBox *m_autoStart = nullptr;
    QCheckBox *m_notifications = nullptr;
    QListWidget *m_providerList = nullptr;
    QMap<QString, QJsonObject> m_providerMap;
    QListWidget *m_collectionList = nullptr;
    QMap<QString, QJsonObject> m_collectionMap;
    bool m_dirty = false;
};
