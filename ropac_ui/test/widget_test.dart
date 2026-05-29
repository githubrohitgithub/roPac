import 'package:flutter_test/flutter_test.dart';
import 'package:ropac_ui/services/ropac_local.dart';

void main() {
  test('RopacPaths config path is defined', () {
    expect(RopacPaths.configFile(), contains('ropac_root.txt'));
  });
}
