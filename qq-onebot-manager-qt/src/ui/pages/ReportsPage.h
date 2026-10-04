#pragma once
#include <QWidget>

class QLabel;
class QPlainTextEdit;
class QListWidget;
class QPushButton;

class ReportsPage : public QWidget {
    Q_OBJECT
public:
    explicit ReportsPage(QWidget *parent = nullptr);
    void setPreview(const QString &text);
    void setNextTime(const QString &text);
    void setCategories(const QVariantList &categories);
    void setViewStatus(const QString &text);
    void setBackupStatus(const QString &text);
signals:
    void previewRequested();
    void sendRequested();
    void openRequested(const QString &relativePath);
    void viewRequested();
    void backupRequested();
private:
    QLabel *m_nextTime = nullptr;
    QPlainTextEdit *m_preview = nullptr;
    QListWidget *m_categories = nullptr;
    QLabel *m_viewStatus = nullptr;
    QPushButton *m_rebuild = nullptr;
    QLabel *m_backupStatus = nullptr;
    QPushButton *m_backup = nullptr;
};
