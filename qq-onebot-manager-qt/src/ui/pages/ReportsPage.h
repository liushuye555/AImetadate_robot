#pragma once
#include <QWidget>

class QLabel;
class QPlainTextEdit;
class QListWidget;

class ReportsPage : public QWidget {
    Q_OBJECT
public:
    explicit ReportsPage(QWidget *parent = nullptr);
    void setPreview(const QString &text);
    void setNextTime(const QString &text);
    void setCategories(const QVariantList &categories);
signals:
    void previewRequested();
    void sendRequested();
    void openRequested(const QString &relativePath);
    void viewRequested();
private:
    QLabel *m_nextTime = nullptr;
    QPlainTextEdit *m_preview = nullptr;
    QListWidget *m_categories = nullptr;
};
