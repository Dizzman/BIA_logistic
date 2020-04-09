import sys

import zipfile, os

"""
Archive directory directory_to_archive to zip_directory/zip_filename file
archive structure have upper directory with name of zip_filename without zip extension

Example:

output/outer/linear.lp
output/outer/linear2.lp
output/outer/inner/nonlinear.xz
output/result.xsl

dir_to_zip('/tmp/archive', '2019-02-03.zip', '../output/')

/tmp/archive/2019-02-03.zip

Content:

2019-02-03/result.xsl
2019-02-03/outer/linear.lp
2019-02-03/outer/linear2.lp
2019-02-03/outer/inner/nonlinear.xz
"""
def dir_to_zip(zip_directory, zip_filename, directory_to_archive, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(os.path.join(zip_directory, zip_filename), 'w', compression=compression) as zip_archive:
        for root, dirs, files in os.walk(directory_to_archive):
            for filename in files:
                name_in_archive = os.path.normpath(  # delete indentity relative paths, like /./ for first root
                    os.path.join(
                        # filename without extension
                        os.path.splitext(os.path.basename(zip_filename))[0],
                        # directory path without relative paths of system pwd (see os.walk help)
                        os.path.relpath(root, directory_to_archive),
                        filename))

                path_to_file = os.path.join(root, filename)

                zip_archive.write(
                    filename=path_to_file,
                    arcname=name_in_archive)
