#pragma once
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
    void setSchema(const QVariant &schema);
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
    void rebuildCollectionList();
    void rebuildCustomRuleList();
    void markDirty();
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    QPushButton *m_collectionToggle = nullptr;
    bool m_collectionPaused = false;
    QCheckBox *m_expandForwards = nullptr;
    QListWidget *m_collectionList = nullptr;
    QMap<QString, QJsonObject> m_collectionMap;
    QListWidget *m_customRuleList = nullptr;
    QJsonArray m_customRules;
    QMap<QString, QCheckBox *> m_templateBoxes;
    bool m_dirty = false;
};
