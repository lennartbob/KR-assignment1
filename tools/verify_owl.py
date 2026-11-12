"""Export HermiT results using the OWLAPI and HermiT jars installed with Protégé."""

import argparse
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def verify(protege, output, java, compiler):
    bundles = sorted((protege / "bundles").glob("*.jar"))
    hermit, = (protege / "plugins").glob("org.semanticweb.hermit-*.jar")
    owlapi = protege / "bundles" / "owlapi-osgidistribution.jar"
    with TemporaryDirectory(prefix="safeslice-owl-") as temporary:
        folder = Path(temporary)
        nested_jars = []
        for bundle in (owlapi, hermit):
            with ZipFile(bundle) as archive:
                for name in archive.namelist():
                    if name.endswith(".jar"):
                        destination = folder / Path(name).name
                        destination.write_bytes(archive.read(name))
                        nested_jars.append(destination)
        # Protégé's desktop configuration enables debug logging by default.
        config = folder / "logback.xml"
        config.write_text('<configuration><root level="WARN"/></configuration>', encoding="utf-8")
        classpath = os.pathsep.join(map(str, [folder, *bundles, hermit, *nested_jars]))
        source = str(ROOT / "tools" / "VerifyOntology.java")
        if compiler:
            subprocess.run([java, "-jar", str(compiler), "-11", "-proc:none",
                            "-classpath", classpath, "-d", temporary, source], check=True)
        subprocess.run([
            java, "-Xmx2g", f"-Dlogback.configurationFile={config}", "-cp", classpath,
            "VerifyOntology" if compiler else source, str(ROOT / "code.rdf"), str(output.resolve()),
        ], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protege", type=Path, help="Protégé installation containing bundles and plugins")
    parser.add_argument("output", type=Path, help="Directory for the CSV results")
    parser.add_argument("--java", default="java", help="Java 11+ executable from a JDK")
    parser.add_argument("--compiler", type=Path,
                        help="Eclipse ECJ jar for using the Java runtime bundled with Protégé")
    args = parser.parse_args()
    verify(args.protege, args.output, args.java, args.compiler)
