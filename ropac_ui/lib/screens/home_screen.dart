import 'dart:async';

import 'package:flutter/material.dart';

import '../services/model_controller.dart';
import '../services/ropac_local.dart';
import '../theme/ropac_theme.dart';
import 'chat_screen.dart';
import 'model_screen.dart';
import 'train_screen.dart';

const _sidebarExpandedWidth = 220.0;
const _sidebarCollapsedWidth = 52.0;

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.ropac});

  final RopacLocal ropac;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  final _model = ModelController();
  int _index = 0;
  bool _didAutoCollapseOnReady = false;
  late final AnimationController _sidebarAnim;
  late final Animation<double> _sidebarWidth;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_checkPersonalDataDeps());
    _sidebarAnim = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 160),
      value: 1,
    );
    _sidebarWidth = Tween<double>(
      begin: _sidebarCollapsedWidth,
      end: _sidebarExpandedWidth,
    ).animate(CurvedAnimation(
      parent: _sidebarAnim,
      curve: Curves.easeInOut,
    ));
    _model.addListener(_onModelChanged);
    unawaited(_model.loadCatalog(widget.ropac));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(widget.ropac.lockVault());
    _model.removeListener(_onModelChanged);
    _sidebarAnim.dispose();
    _model.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.detached) {
      unawaited(widget.ropac.lockVault());
    }
  }

  Future<void> _checkPersonalDataDeps() async {
    try {
      final r = await widget.ropac.personalDataSetup();
      if (!mounted || r['deps_ok'] == true) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(
            r['message']?.toString() ??
                'Run ./install.sh in the RoPac folder.',
          ),
        ),
      );
    } catch (_) {}
  }

  void _onModelChanged() {
    final ready = _model.isReady;
    if (ready && !_didAutoCollapseOnReady && _sidebarAnim.value > 0.5) {
      _didAutoCollapseOnReady = true;
      _sidebarAnim.reverse();
    }
  }

  void _toggleSidebar() {
    if (_sidebarAnim.isAnimating) {
      _sidebarAnim.stop();
    }
    if (_sidebarAnim.value > 0.5) {
      _sidebarAnim.reverse();
    } else {
      _sidebarAnim.forward();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: RoPacTheme.pageBackground(),
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: SafeArea(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              RepaintBoundary(
                child: _RoPacSidebar(
                  widthAnimation: _sidebarWidth,
                  index: _index,
                  model: _model,
                  onToggle: _toggleSidebar,
                  onSelectTab: (i) => setState(() => _index = i),
                  ropac: widget.ropac,
                  onStart: () => _model.start(widget.ropac),
                  onStop: () => _model.stop(widget.ropac),
                ),
              ),
              Expanded(
                child: RepaintBoundary(
                  child: Stack(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(8, 8, 12, 8),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(20),
                          child: IndexedStack(
                            index: _index,
                            children: [
                              ChatScreen(ropac: widget.ropac),
                              TrainScreen(ropac: widget.ropac),
                              ModelScreen(
                                ropac: widget.ropac,
                                model: _model,
                                onOpenFolderSettings: () =>
                                    _openSettings(context),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openSettings(BuildContext context) async {
    final controller = TextEditingController(text: widget.ropac.ropacRoot);
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: RoPacColors.surfaceHigh,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text(
          'RoPac folder',
          style: TextStyle(color: RoPacColors.textPrimary),
        ),
        content: TextField(
          controller: controller,
          style: const TextStyle(color: RoPacColors.textPrimary),
          decoration: const InputDecoration(hintText: '/path/to/ropac'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (saved == true && context.mounted) {
      await RopacPaths.saveRoot(controller.text.trim());
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: RoPacColors.surfaceHigh,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          content: const Text('Restart app to use new folder'),
        ),
      );
    }
    controller.dispose();
  }
}

class _RoPacSidebar extends StatelessWidget {
  const _RoPacSidebar({
    required this.widthAnimation,
    required this.index,
    required this.model,
    required this.ropac,
    required this.onToggle,
    required this.onSelectTab,
    required this.onStart,
    required this.onStop,
  });

  final Animation<double> widthAnimation;
  final int index;
  final ModelController model;
  final RopacLocal ropac;
  final VoidCallback onToggle;
  final ValueChanged<int> onSelectTab;
  final VoidCallback onStart;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widthAnimation,
      builder: (context, _) {
        final w = widthAnimation.value;
        final sidebarOpen = w > 0.55 * _sidebarExpandedWidth;
        final showLabels = w > 118;
        final showModelPanel = w > 150;

        return SizedBox(
          width: w,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: RoPacColors.surface.withValues(alpha: 0.92),
              border: const Border(
                right: BorderSide(color: RoPacColors.border),
              ),
            ),
            child: ClipRect(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(6, 8, 6, 4),
                    child: Row(
                      children: [
                        IconButton(
                          tooltip:
                              sidebarOpen ? 'Close sidebar' : 'Open sidebar',
                          onPressed: onToggle,
                          visualDensity: VisualDensity.compact,
                          icon: Icon(
                            sidebarOpen
                                ? Icons.chevron_left_rounded
                                : Icons.menu_rounded,
                            size: 20,
                            color: RoPacColors.textMuted,
                          ),
                        ),
                        if (showLabels)
                          const Expanded(
                            child: Text(
                              'RoPac',
                              style: TextStyle(
                                color: RoPacColors.textPrimary,
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  _SidebarNavItem(
                    icon: Icons.forum_outlined,
                    selectedIcon: Icons.forum_rounded,
                    label: 'Chat',
                    selected: index == 0,
                    showLabel: showLabels,
                    enabled: true,
                    onTap: () => onSelectTab(0),
                  ),
                  _SidebarNavItem(
                    icon: Icons.hub_outlined,
                    selectedIcon: Icons.hub_rounded,
                    label: 'Train',
                    selected: index == 1,
                    showLabel: showLabels,
                    enabled: true,
                    onTap: () => onSelectTab(1),
                  ),
                  _SidebarNavItem(
                    icon: Icons.memory_outlined,
                    selectedIcon: Icons.memory_rounded,
                    label: 'Model',
                    selected: index == 2,
                    showLabel: showLabels,
                    enabled: true,
                    onTap: () => onSelectTab(2),
                  ),
                  const Spacer(),
                  ListenableBuilder(
                    listenable: model,
                    builder: (context, _) {
                      if (showModelPanel) {
                        return _ModelSidebarPanel(
                          model: model,
                          onStart: onStart,
                          onStop: onStop,
                        );
                      }
                      return _ModelSidebarRail(
                        model: model,
                        onExpand: onToggle,
                      );
                    },
                  ),
                  const SizedBox(height: 8),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _SidebarNavItem extends StatelessWidget {
  const _SidebarNavItem({
    required this.icon,
    required this.selectedIcon,
    required this.label,
    required this.selected,
    required this.showLabel,
    required this.enabled,
    required this.onTap,
  });

  final IconData icon;
  final IconData selectedIcon;
  final String label;
  final bool selected;
  final bool showLabel;
  final bool enabled;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final color = !enabled
        ? RoPacColors.textMuted.withValues(alpha: 0.35)
        : selected
            ? RoPacColors.accent
            : RoPacColors.textMuted;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      child: Material(
        color: selected && enabled
            ? RoPacColors.accent.withValues(alpha: 0.12)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          onTap: enabled ? onTap : null,
          borderRadius: BorderRadius.circular(10),
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: showLabel ? 12 : 0,
              vertical: 10,
            ),
            child: showLabel
                ? Row(
                    children: [
                      Icon(
                        selected ? selectedIcon : icon,
                        size: 20,
                        color: color,
                      ),
                      const SizedBox(width: 12),
                      Text(
                        label,
                        style: TextStyle(
                          color: color,
                          fontSize: 14,
                          fontWeight:
                              selected ? FontWeight.w600 : FontWeight.w500,
                        ),
                      ),
                    ],
                  )
                : Center(
                    child: Icon(
                      selected ? selectedIcon : icon,
                      size: 22,
                      color: color,
                    ),
                  ),
          ),
        ),
      ),
    );
  }
}

class _ModelSidebarPanel extends StatelessWidget {
  const _ModelSidebarPanel({
    required this.model,
    required this.onStart,
    required this.onStop,
  });

  final ModelController model;
  final VoidCallback onStart;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    final ready = model.state == ModelRunState.ready;
    final busy = model.isBusy;

    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 0, 10, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Divider(height: 1, color: RoPacColors.border),
          const SizedBox(height: 8),
          _ActionButton(
            label: 'Start model',
            shortLabel: 'Start',
            icon: Icons.play_arrow_rounded,
            gradient: const LinearGradient(
              colors: [Color(0xFF0891B2), Color(0xFF22D3EE)],
            ),
            enabled: !ready && !busy,
            loading: busy && model.state == ModelRunState.starting,
            onPressed: onStart,
          ),
          const SizedBox(height: 6),
          _ActionButton(
            label: 'Stop model',
            shortLabel: 'Stop',
            icon: Icons.stop_rounded,
            gradient: LinearGradient(
              colors: [
                RoPacColors.danger.withValues(alpha: 0.85),
                RoPacColors.danger,
              ],
            ),
            enabled: ready && !busy,
            loading: busy && model.state == ModelRunState.stopping,
            onPressed: onStop,
            outlined: true,
          ),
        ],
      ),
    );
  }
}

class _ModelSidebarRail extends StatelessWidget {
  const _ModelSidebarRail({
    required this.model,
    required this.onExpand,
  });

  final ModelController model;
  final VoidCallback onExpand;

  @override
  Widget build(BuildContext context) {
    final ready = model.state == ModelRunState.ready;
    final color = ready ? RoPacColors.accentGreen : RoPacColors.textMuted;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Column(
        children: [
          const Divider(height: 1, color: RoPacColors.border),
          const SizedBox(height: 8),
          IconButton(
            tooltip: 'Model & settings',
            onPressed: onExpand,
            icon: Icon(
              ready ? Icons.bolt_rounded : Icons.power_settings_new_rounded,
              color: color,
              size: 22,
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.label,
    required this.shortLabel,
    required this.icon,
    required this.gradient,
    required this.enabled,
    required this.onPressed,
    this.loading = false,
    this.outlined = false,
  });

  final String label;
  final String shortLabel;
  final IconData icon;
  final Gradient gradient;
  final bool enabled;
  final bool loading;
  final VoidCallback onPressed;
  final bool outlined;

  @override
  Widget build(BuildContext context) {
    final content = Row(
      mainAxisAlignment: MainAxisAlignment.center,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (loading)
          const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: Colors.white,
            ),
          )
        else
          Icon(icon, size: 16),
        const SizedBox(width: 5),
        Flexible(
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12),
          ),
        ),
      ],
    );

    const btnHeight = 32.0;
    const btnRadius = 10.0;

    if (!enabled) {
      return Container(
        height: btnHeight,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: RoPacColors.surfaceHigh.withValues(alpha: 0.5),
          borderRadius: BorderRadius.circular(btnRadius),
          border: Border.all(color: RoPacColors.border),
        ),
        child: DefaultTextStyle(
          style: TextStyle(color: RoPacColors.textMuted.withValues(alpha: 0.5)),
          child: content,
        ),
      );
    }

    if (outlined) {
      return Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(btnRadius),
          child: Ink(
            height: btnHeight,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(btnRadius),
              border: Border.all(
                color: RoPacColors.danger.withValues(alpha: 0.6),
              ),
              color: RoPacColors.danger.withValues(alpha: 0.12),
            ),
            child: Center(
              child: DefaultTextStyle(
                style: const TextStyle(color: RoPacColors.danger),
                child: content,
              ),
            ),
          ),
        ),
      );
    }

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(btnRadius),
        child: Ink(
          height: btnHeight,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            gradient: gradient,
            borderRadius: BorderRadius.circular(btnRadius),
            boxShadow: [
              BoxShadow(
                color: RoPacColors.accent.withValues(alpha: 0.25),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Center(
            child: DefaultTextStyle(
              style: const TextStyle(color: Colors.white),
              child: content,
            ),
          ),
        ),
      ),
    );
  }
}

