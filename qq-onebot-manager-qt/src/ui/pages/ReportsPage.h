#pragma once
#include <QWidget>

class QLabel;
class QPlainTextEdit;

class ReportsPage : public QWidget {
    Q_OBJECT
public:
    explicit ReportsPage(QWidget *parent = nullptr);
    void setPreview(const QString &text);
    void setNextTime(const QString &text);
signals:
    void previewRequested();
    void sendRequested();
    void openRequested(const QString &relativePath);
private:
    QLabel *m_nextTime = nullptr;
    QPlainTextEdit *m_preview = nullptr;
};
