#pragma once
#include <QWidget>
#include <QJsonObject>
#include <QJsonArray>
#include <QHash>
#include <QMap>

class QVBoxLayout;
class QPushButton;
class QLabel;
class QComboBox;
class QCheckBox;
class QPlainTextEdit;
class QListWidget;

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
private:
    QJsonObject buildPatch() const;
    QWidget *buildGeneralSection();
    QWidget *buildProviderSection();
    QJsonObject buildProvidersObject() const;
    void openProviderDialog(const QString &editName);
    void rebuildProviderList();
    void markDirty();
    QVBoxLayout *m_sections = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    QHash<QString, QWidget *> m_fields;
    QComboBox *m_language = nullptr;
    QComboBox *m_theme = nullptr;
    QCheckBox *m_autoStart = nullptr;
    QCheckBox *m_notifications = nullptr;
    QListWidget *m_providerList = nullptr;
    QMap<QString, QJsonObject> m_providerMap;
    bool m_dirty = false;
};
