#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QMap>
#include <QStringList>
#include <QWidget>

class QCheckBox;
class QLabel;
class QListWidget;
class QPlainTextEdit;
class QPushButton;
class QSpinBox;

class ChatPage : public QWidget {
    Q_OBJECT
public:
    explicit ChatPage(QWidget *parent = nullptr);
    void setSchema(bool ok, const QVariant &schema);
    void setGroups(const QVariantList &groups);
    void setSavedMessage(const QString &text);
signals:
    void saveRequested(QJsonObject patch);
    void groupsScanRequested();
private:
    void fillGroupList(QListWidget *list, const QJsonArray &ids);
    QStringList groupIds(QListWidget *list) const;
    void markDirty();
    QCheckBox *m_enabled = nullptr;
    QPlainTextEdit *m_persona = nullptr;
    QListWidget *m_groups = nullptr;
    QMap<QString, QString> m_groupNames;
    QSpinBox *m_memoryTurns = nullptr;
    QSpinBox *m_adminMemoryTurns = nullptr;
    QSpinBox *m_cooldown = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    bool m_schemaLoaded = false;
};
