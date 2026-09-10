package com.yt.downloader;

import android.Manifest;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends AppCompatActivity {

    private static final String PREFS_NAME = "YtDownloaderPrefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String DEFAULT_URL = "http://192.168.1.15:5000";

    private static final int PERMISSION_REQUEST_STORAGE = 101;
    private static final int PERMISSION_REQUEST_NOTIF = 102;

    private WebView webView;
    private ProgressBar progressBar;
    private SwipeRefreshLayout swipeRefresh;
    private View layoutError;
    private TextView txtCurrentServer;
    private SharedPreferences prefs;

    private String pendingSharedUrl = null;
    private String pendingDownloadUrl = null;
    private String pendingDownloadMime = null;
    private String pendingDownloadContentDisposition = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);

        webView = findViewById(R.id.webView);
        progressBar = findViewById(R.id.progressBar);
        swipeRefresh = findViewById(R.id.swipeRefresh);
        layoutError = findViewById(R.id.layoutError);
        txtCurrentServer = findViewById(R.id.txtCurrentServer);
        Button btnChangeServer = findViewById(R.id.btnChangeServer);
        Button btnRetry = findViewById(R.id.btnRetry);

        setupWebView();
        setupListeners();
        handleIncomingIntent(getIntent());

        btnChangeServer.setOnClickListener(v -> showServerConfigDialog());
        btnRetry.setOnClickListener(v -> loadActiveUrl());

        // Back navigation handler
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack();
                } else {
                    finish();
                }
            }
        });

        // Request notification permission for Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        PERMISSION_REQUEST_NOTIF);
            }
        }

        loadActiveUrl();
    }

    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (newProgress < 100) {
                    progressBar.setVisibility(View.VISIBLE);
                    progressBar.setProgress(newProgress);
                } else {
                    progressBar.setVisibility(View.GONE);
                }
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                swipeRefresh.setRefreshing(false);
                layoutError.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);

                if (pendingSharedUrl != null) {
                    injectSharedUrl(pendingSharedUrl);
                    pendingSharedUrl = null;
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    swipeRefresh.setRefreshing(false);
                    webView.setVisibility(View.GONE);
                    layoutError.setVisibility(View.VISIBLE);
                    txtCurrentServer.setText("Could not reach:\n" + getServerUrl());
                }
            }
        });

        // Download handling via Android DownloadManager
        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            pendingDownloadUrl = url;
            pendingDownloadContentDisposition = contentDisposition;
            pendingDownloadMime = mimetype;

            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P &&
                    ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE)
                            != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE},
                        PERMISSION_REQUEST_STORAGE);
            } else {
                startNativeDownload(url, contentDisposition, mimetype);
            }
        });
    }

    private void setupListeners() {
        swipeRefresh.setOnRefreshListener(() -> {
            layoutError.setVisibility(View.GONE);
            webView.reload();
        });
    }

    private void startNativeDownload(String url, String contentDisposition, String mimetype) {
        try {
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
            String fileName = URLUtil.guessFileName(url, contentDisposition, mimetype);
            if (fileName == null || fileName.isEmpty() || fileName.endsWith(".bin")) {
                fileName = "video_" + System.currentTimeMillis() + ".mp4";
            }

            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) {
                request.addRequestHeader("Cookie", cookie);
            }

            request.setTitle(fileName);
            request.setDescription("Downloading video via HD Downloader...");
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
            request.allowScanningByMediaScanner();

            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm != null) {
                dm.enqueue(request);
                Toast.makeText(this, "⬇️ Download started: " + fileName, Toast.LENGTH_LONG).show();
            }
        } catch (Exception e) {
            Toast.makeText(this, "Download error: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIncomingIntent(intent);
        if (pendingSharedUrl != null) {
            injectSharedUrl(pendingSharedUrl);
            pendingSharedUrl = null;
        }
    }

    private void handleIncomingIntent(Intent intent) {
        if (intent != null && Intent.ACTION_SEND.equals(intent.getAction())
                && "text/plain".equals(intent.getType())) {
            String sharedText = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (sharedText != null) {
                String extracted = extractUrl(sharedText);
                pendingSharedUrl = (extracted != null) ? extracted : sharedText;
            }
        }
    }

    private String extractUrl(String text) {
        Pattern pattern = Pattern.compile("(https?://[\\w\\d:#@%/;$()~_?\\+-=\\\\.&]+)", Pattern.CASE_INSENSITIVE);
        Matcher matcher = pattern.matcher(text);
        if (matcher.find()) {
            return matcher.group(1);
        }
        return null;
    }

    private void injectSharedUrl(String url) {
        if (url == null || url.trim().isEmpty()) return;
        String safeUrl = url.replace("'", "\\'");
        String js = "setTimeout(function() {" +
                "  var inp = document.getElementById('url-input') || document.querySelector('input[type=\"url\"]') || document.querySelector('input[type=\"text\"]');" +
                "  if (inp) {" +
                "    inp.value = '" + safeUrl + "';" +
                "    var btn = document.getElementById('fetch-btn');" +
                "    if (btn) btn.click();" +
                "  }" +
                "}, 600);";
        webView.evaluateJavascript(js, null);
    }

    private String getServerUrl() {
        return prefs.getString(KEY_SERVER_URL, DEFAULT_URL);
    }

    private void setServerUrl(String url) {
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        prefs.edit().putString(KEY_SERVER_URL, url.trim()).apply();
        loadActiveUrl();
    }

    private void loadActiveUrl() {
        String url = getServerUrl();
        layoutError.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(url);
    }

    private void showServerConfigDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle(R.string.server_dialog_title);

        LayoutInflater inflater = getLayoutInflater();
        View dialogView = inflater.inflate(R.layout.dialog_change_url, null);
        builder.setView(dialogView);

        EditText editUrl = dialogView.findViewById(R.id.editServerUrl);
        editUrl.setText(getServerUrl());
        editUrl.setSelection(editUrl.getText().length());

        builder.setPositiveButton(R.string.server_dialog_save, (dialog, which) -> {
            String newUrl = editUrl.getText().toString().trim();
            if (!newUrl.isEmpty()) {
                setServerUrl(newUrl);
            }
        });

        builder.setNegativeButton(R.string.server_dialog_cancel, (dialog, which) -> dialog.dismiss());
        builder.create().show();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.main_menu, menu);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        int id = item.getItemId();
        if (id == R.id.action_refresh) {
            webView.reload();
            return true;
        } else if (id == R.id.action_change_url) {
            showServerConfigDialog();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PERMISSION_REQUEST_STORAGE) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                if (pendingDownloadUrl != null) {
                    startNativeDownload(pendingDownloadUrl, pendingDownloadContentDisposition, pendingDownloadMime);
                    pendingDownloadUrl = null;
                }
            } else {
                Toast.makeText(this, "Storage permission is required to save downloads.", Toast.LENGTH_SHORT).show();
            }
        }
    }
}
