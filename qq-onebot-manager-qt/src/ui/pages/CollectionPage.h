#pragma once
#include <QSet>
#include <QStringList>
#include <QWidget>
#include <QJsonArray>
#include <QJsonObject>
#include <QMap>

class QCheckBox;
class QListWidget;
class QPushButton;
class QLabel;

class CollectionPage : public QWidget {
    Q_OBJECT
public:
    explicit CollectionPage(QWidget *parent = nullptr);
    void setSchema(bool ok, const QVariant &schema);
    void setConfig(const QJsonObject &config);
    void setGroups(const QVariantList &groups);
    void setCollectionPaused(bool paused);
    void setSavedMessage(const QString &text);
    bool collectionChecked() const;
signals:
    void saveRequested(QJsonObject patch);
    void groupsScanRequested();
    void collectionToggle();
private:
    QJsonObject buildPatch() const;
    void openCollectionDialog(const QString &editGroup);
    void openCustomRuleDialog(int editIndex);
    void openKnowledgeDialog(const QString &scope);
    void rebuildKnowledgeList();
    void removeKnowledgeGroup();
    void rebuildCollectionList();
    void rebuildCustomRuleList();
    void batchSetEnabled(bool enabled);
    void batchRemove();
    void markDirty();
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    QPushButton *m_collectionToggle = nullptr;
    bool m_collectionPaused = false;
    QCheckBox *m_expandForwards = nullptr;
    QCheckBox *m_knowledgeEnabled = nullptr;
    QListWidget *m_knowledgeList = nullptr;
    QLabel *m_knowledgeEmpty = nullptr;
    QJsonObject m_knowledgeGroups;
    QJsonObject m_knowledgeDefaults;
    QStringList m_knowledgeProviderOptions;
    QSet<QString> m_removedKnowledgeGroups;
    QStringList m_knowledgeAvailableGroups;
    bool m_knowledgeScanPending = false;
    bool m_suppressKnowledgeChange = false;
    bool m_loadingConfig = false;
    QListWidget *m_collectionList = nullptr;
    QMap<QString, QJsonObject> m_collectionMap;
    QListWidget *m_customRuleList = nullptr;
    QJsonArray m_customRules;
    QStringList m_groupIds;
    QMap<QString, QString> m_groupNames;
    QSet<QString> m_blockedGroups;
    bool m_suppressRuleChange = false;
    QMap<QString, QCheckBox *> m_templateBoxes;
    bool m_suppressGroupChange = false;
    bool m_schemaLoaded = false;
    bool m_dirty = false;
};
